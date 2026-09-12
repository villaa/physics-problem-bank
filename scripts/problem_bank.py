"""Shared logic for managing docs/data/problems.json, its PDFs, and the
Cloudflare-backed protected problems. Used by both problems.py (CLI) and
admin/server.py (local web UI) so the two stay in sync automatically.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA_FILE = DOCS / "data" / "problems.json"
SCHEMA_FILE = DOCS / "data" / "schema.json"
PROBLEMS_DIR = DOCS / "problems"
WORKER_DIR = ROOT / "worker"
R2_BUCKET = "physics-problem-bank-protected"
REFERENCES_FILE = ROOT / "admin" / "references.json"


class ProblemBankError(Exception):
    """Raised for any user-facing error (bad input, missing file, wrangler
    failure, ...). Callers show `str(e)` to the user."""


def load_problems():
    return json.loads(DATA_FILE.read_text())


def save_problems(problems):
    DATA_FILE.write_text(json.dumps(problems, indent=2) + "\n")


def load_schema():
    return json.loads(SCHEMA_FILE.read_text())


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def validate_entry(entry, schema, existing_ids):
    errors = []
    for field, spec in schema["fields"].items():
        if spec.get("required") and field not in entry:
            errors.append(f"missing required field '{field}'")
    for field, value in entry.items():
        spec = schema["fields"].get(field)
        if not spec:
            errors.append(f"unknown field '{field}' (not in docs/data/schema.json)")
            continue
        if spec["type"] == "string" and not isinstance(value, str):
            errors.append(f"'{field}' should be a string")
        if spec["type"] == "array" and not isinstance(value, list):
            errors.append(f"'{field}' should be an array")
        if spec["type"] == "boolean" and not isinstance(value, bool):
            errors.append(f"'{field}' should be true/false")
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"'{field}' must be one of {spec['enum']}, got '{value}'")
    if entry.get("id") in existing_ids:
        errors.append(f"duplicate id '{entry.get('id')}'")
    return errors


def wrangler(*args, confirm=False):
    npx = shutil.which("npx")
    if not npx:
        raise ProblemBankError("'npx' not found on PATH (needed to run wrangler)")
    cmd = [npx, "wrangler", *args]
    result = subprocess.run(
        cmd,
        cwd=WORKER_DIR,
        input="y\n" if confirm else None,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ProblemBankError(
            f"wrangler command failed: {' '.join(args)}\n{result.stderr or result.stdout}"
        )
    return result.stdout


def sha256_hex(s):
    return hashlib.sha256(s.encode()).hexdigest()


def add_problem(
    *,
    id,
    subject,
    topic,
    difficulty,
    type,
    statement_path,
    solutions=None,
    tags=None,
    source="",
    protected=False,
    key=None,
):
    """solutions: list of (method, Path) tuples. Paths must already exist.
    Raises ProblemBankError on any failure; does nothing partial on the
    metadata side (problems.json is only written after all uploads/copies
    succeed) - though a protected add can still leave some KV/R2 writes in
    place if a later step fails, since Cloudflare has no multi-write
    transactions; re-running 'add' with the same id is safe (it overwrites)."""
    problems = load_problems()
    schema = load_schema()

    if any(p["id"] == id for p in problems):
        raise ProblemBankError(f"id '{id}' already exists. Remove it first or pick a new id.")

    solutions = solutions or []
    entry = {
        "id": id,
        "subject": subject,
        "topic": topic,
        "tags": tags or [],
        "difficulty": difficulty,
        "type": type,
        "statement_pdf": "statement.pdf",
        "solutions": [
            {"method": m, "pdf": f"solutions/{slugify(m)}.pdf"} for m, _ in solutions
        ],
        "source": source or "",
        "protected": bool(protected),
    }

    errors = validate_entry(entry, schema, {p["id"] for p in problems})
    if errors:
        raise ProblemBankError("Entry fails schema validation:\n" + "\n".join(f"- {e}" for e in errors))

    statement_path = Path(statement_path).expanduser()
    if not statement_path.exists():
        raise ProblemBankError(f"statement PDF not found: {statement_path}")
    for _, path in solutions:
        if not Path(path).exists():
            raise ProblemBankError(f"solution PDF not found: {path}")

    if protected:
        if not key:
            raise ProblemBankError("protected problems require an access key")
        key_hash = sha256_hex(key)
        wrangler(
            "kv", "key", "put", "--binding=PROBLEM_KEYS", id,
            json.dumps({"keyHash": key_hash}), "--remote",
        )
        wrangler(
            "r2", "object", "put",
            f"{R2_BUCKET}/{id}/statement.pdf",
            f"--file={statement_path.resolve()}", "--remote",
        )
        for method, path in solutions:
            wrangler(
                "r2", "object", "put",
                f"{R2_BUCKET}/{id}/solutions/{slugify(method)}.pdf",
                f"--file={Path(path).resolve()}", "--remote",
            )
    else:
        dest = PROBLEMS_DIR / id
        (dest / "solutions").mkdir(parents=True, exist_ok=True)
        shutil.copy(statement_path, dest / "statement.pdf")
        for method, path in solutions:
            shutil.copy(path, dest / "solutions" / f"{slugify(method)}.pdf")

    problems.append(entry)
    save_problems(problems)
    return entry


def remove_problem(id):
    problems = load_problems()
    match = next((p for p in problems if p["id"] == id), None)
    if not match:
        raise ProblemBankError(f"no problem with id '{id}'")

    if match.get("protected"):
        wrangler("kv", "key", "delete", "--binding=PROBLEM_KEYS", id, "--remote", confirm=True)
        wrangler("r2", "object", "delete", f"{R2_BUCKET}/{id}/statement.pdf", "--remote")
        for sol in match.get("solutions", []):
            wrangler("r2", "object", "delete", f"{R2_BUCKET}/{id}/{sol['pdf']}", "--remote")
    else:
        dest = PROBLEMS_DIR / id
        if dest.exists():
            shutil.rmtree(dest)

    problems = [p for p in problems if p["id"] != id]
    save_problems(problems)
    return match


def validate_all():
    """Returns {problem_id: [error, ...]} for entries with any problems."""
    problems = load_problems()
    schema = load_schema()
    seen = set()
    results = {}
    for entry in problems:
        errors = validate_entry(entry, schema, seen)
        seen.add(entry.get("id"))
        pid = entry.get("id", "<no id>")

        if not entry.get("protected"):
            base = PROBLEMS_DIR / pid
            stmt = base / entry.get("statement_pdf", "statement.pdf")
            if not stmt.exists():
                errors.append(f"statement PDF not found: {stmt.relative_to(ROOT)}")
            for sol in entry.get("solutions", []):
                sp = base / sol.get("pdf", "")
                if not sp.exists():
                    errors.append(f"solution PDF not found: {sp.relative_to(ROOT)}")

        if errors:
            results[pid] = errors
    return results


def list_problems(subject=None, protected_only=False):
    problems = load_problems()
    return [
        p for p in problems
        if (not subject or p.get("subject") == subject)
        and (not protected_only or p.get("protected"))
    ]


def load_references():
    """Reusable base citations (e.g. textbook editions), independent of any
    one problem's section/page - kept separate so they don't accumulate
    duplicates the way full 'source' strings would (page numbers differ per
    problem)."""
    if not REFERENCES_FILE.exists():
        return []
    return json.loads(REFERENCES_FILE.read_text())


def save_references(refs):
    REFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCES_FILE.write_text(json.dumps(sorted(refs, key=str.lower), indent=2) + "\n")


def add_reference(text):
    text = text.strip()
    if not text:
        raise ProblemBankError("reference text cannot be empty")
    refs = load_references()
    if text in refs:
        raise ProblemBankError(f"reference already exists: {text}")
    refs.append(text)
    save_references(refs)
    return refs


def remove_reference(text):
    refs = load_references()
    if text not in refs:
        raise ProblemBankError(f"reference not found: {text}")
    refs.remove(text)
    save_references(refs)
    return refs
