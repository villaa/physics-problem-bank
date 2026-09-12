"""Shared logic for managing docs/data/problems.json, its PDFs, and the
Cloudflare-backed protected problems. Used by both problems.py (CLI) and
admin/server.py (local web UI) so the two stay in sync automatically.
"""
import hashlib
import json
import re
import secrets
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
        encoding="utf-8",
        errors="replace",
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
):
    """solutions: list of (method, Path) tuples. Paths must already exist.

    The statement is always public, even for a 'protected' problem -
    protection only ever gates the solutions, via a pool of one-time keys
    (see generate_keys). A freshly-added protected problem starts with an
    empty key pool; generate_keys adds to it later.

    Raises ProblemBankError on any failure; does nothing partial on the
    metadata side (problems.json is only written after all uploads/copies
    succeed) - though a protected add can still leave a partial R2 upload
    in place if a later step fails, since Cloudflare has no multi-write
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

    # Statement: always a public file, protected or not.
    dest = PROBLEMS_DIR / id
    (dest / "solutions").mkdir(parents=True, exist_ok=True)
    shutil.copy(statement_path, dest / "statement.pdf")

    if protected:
        for method, path in solutions:
            wrangler(
                "r2", "object", "put",
                f"{R2_BUCKET}/{id}/solutions/{slugify(method)}.pdf",
                f"--file={Path(path).resolve()}", "--remote",
            )
    else:
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
        _kv_delete(id)
        for sol in match.get("solutions", []):
            wrangler("r2", "object", "delete", f"{R2_BUCKET}/{id}/{sol['pdf']}", "--remote")

    dest = PROBLEMS_DIR / id
    if dest.exists():
        shutil.rmtree(dest)

    problems = [p for p in problems if p["id"] != id]
    save_problems(problems)
    return match


def _kv_get_key_pool(problem_id):
    """Raw KV read that tolerates a missing key (returns an empty pool)
    instead of raising, since 'no keys generated yet' is a normal state."""
    npx = shutil.which("npx")
    if not npx:
        raise ProblemBankError("'npx' not found on PATH (needed to run wrangler)")
    result = subprocess.run(
        [npx, "wrangler", "kv", "key", "get", "--binding=PROBLEM_KEYS", problem_id, "--remote"],
        cwd=WORKER_DIR,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {"keyHashes": []}
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"keyHashes": []}
    return {"keyHashes": list(parsed.get("keyHashes", []))}


def _kv_put_key_pool(problem_id, pool):
    wrangler(
        "kv", "key", "put", "--binding=PROBLEM_KEYS", problem_id,
        json.dumps(pool), "--remote",
    )


def _kv_delete(problem_id):
    wrangler("kv", "key", "delete", "--binding=PROBLEM_KEYS", problem_id, "--remote", confirm=True)


def generate_keys(problem_id, count):
    """Generates `count` new one-time-use hex keys for a protected problem's
    solutions, adds their hashes to the KV pool, and returns the new
    PLAINTEXT keys - the only time they're ever visible. Distribute them
    immediately; they cannot be recovered afterward, only revoked (by
    removing and re-adding the problem, which clears the whole pool)."""
    if count < 1:
        raise ProblemBankError("count must be at least 1")

    problems = load_problems()
    match = next((p for p in problems if p["id"] == problem_id), None)
    if not match:
        raise ProblemBankError(f"no problem with id '{problem_id}'")
    if not match.get("protected"):
        raise ProblemBankError(f"'{problem_id}' is not a protected problem")

    pool = _kv_get_key_pool(problem_id)
    existing_hashes = set(pool["keyHashes"])

    new_keys = []
    while len(new_keys) < count:
        candidate = secrets.token_hex(4)
        h = sha256_hex(candidate)
        if h in existing_hashes:
            continue
        new_keys.append(candidate)
        existing_hashes.add(h)

    _kv_put_key_pool(problem_id, {"keyHashes": sorted(existing_hashes)})
    return new_keys


def key_count(problem_id):
    """How many unredeemed keys remain for a protected problem."""
    return len(_kv_get_key_pool(problem_id)["keyHashes"])


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

        base = PROBLEMS_DIR / pid
        stmt = base / entry.get("statement_pdf", "statement.pdf")
        if not stmt.exists():
            errors.append(f"statement PDF not found: {stmt.relative_to(ROOT)}")

        if not entry.get("protected"):
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


def _normalize_reference(r):
    """Accepts either the old plain-string format or {label, bibtex}."""
    if isinstance(r, str):
        return {"label": r, "bibtex": ""}
    return {"label": r.get("label", ""), "bibtex": r.get("bibtex", "")}


def load_references():
    """Reusable base citations (e.g. textbook editions), independent of any
    one problem's section/page - kept separate so they don't accumulate
    duplicates the way full 'source' strings would (page numbers differ per
    problem). Each entry is {label, bibtex} - bibtex may be empty."""
    if not REFERENCES_FILE.exists():
        return []
    raw = json.loads(REFERENCES_FILE.read_text())
    return [_normalize_reference(r) for r in raw]


def save_references(refs):
    REFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    refs = sorted(refs, key=lambda r: r["label"].lower())
    REFERENCES_FILE.write_text(json.dumps(refs, indent=2) + "\n")


def add_reference(label, bibtex=""):
    label = label.strip()
    bibtex = (bibtex or "").strip()
    if not label:
        raise ProblemBankError("reference label cannot be empty")
    refs = load_references()
    if any(r["label"] == label for r in refs):
        raise ProblemBankError(f"reference already exists: {label}")
    refs.append({"label": label, "bibtex": bibtex})
    save_references(refs)
    return refs


def remove_reference(label):
    refs = load_references()
    if not any(r["label"] == label for r in refs):
        raise ProblemBankError(f"reference not found: {label}")
    refs = [r for r in refs if r["label"] != label]
    save_references(refs)
    return refs
