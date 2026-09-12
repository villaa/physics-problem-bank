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
import tempfile
from datetime import datetime, timedelta, timezone
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


def _r2_put_from_file(remote_key, src_path):
    wrangler("r2", "object", "put", f"{R2_BUCKET}/{remote_key}", f"--file={src_path}", "--remote")


def _r2_get_to_file(remote_key, dest_path):
    wrangler("r2", "object", "get", f"{R2_BUCKET}/{remote_key}", f"--file={dest_path}", "--remote")


def _r2_delete_best_effort(remote_key):
    try:
        wrangler("r2", "object", "delete", f"{R2_BUCKET}/{remote_key}", "--remote")
    except ProblemBankError:
        pass


def _kv_delete_best_effort(problem_id):
    try:
        _kv_delete(problem_id)
    except ProblemBankError:
        pass


def _remove_solution_file(id, dest, pdf_rel, was_protected):
    if was_protected:
        _r2_delete_best_effort(f"{id}/{pdf_rel}")
    else:
        (dest / pdf_rel).unlink(missing_ok=True)


def update_problem(
    *,
    id,
    subject,
    topic,
    difficulty,
    type,
    solutions,
    statement_path=None,
    tags=None,
    source="",
    protected=False,
):
    """Edits an existing problem's metadata and files in place. `id` cannot
    be changed (renaming would cascade into R2 keys, KV pools, and any
    links already handed out). `solutions` is a list of dicts:
    {"method": str, "file_path": Path|None, "keep_pdf": str|None} -
    keep_pdf is the original entry's relative pdf path when this row is an
    existing solution being kept (renamed and/or replaced), or None for a
    brand-new solution (which then requires file_path). Any of the
    problem's original solutions not referenced by a keep_pdf here are
    deleted. Toggling `protected` moves solution files between the public
    docs/ tree and the private R2 bucket as needed; going from protected
    to public also clears any leftover one-time-key pool (best-effort,
    since an already-missing pool isn't an error)."""
    problems = load_problems()
    schema = load_schema()

    idx = next((i for i, p in enumerate(problems) if p["id"] == id), None)
    if idx is None:
        raise ProblemBankError(f"no problem with id '{id}'")
    old_entry = problems[idx]
    old_protected = bool(old_entry.get("protected"))
    new_protected = bool(protected)
    dest = PROBLEMS_DIR / id
    (dest / "solutions").mkdir(parents=True, exist_ok=True)

    if statement_path:
        statement_path = Path(statement_path).expanduser()
        if not statement_path.exists():
            raise ProblemBankError(f"statement PDF not found: {statement_path}")
        shutil.copy(statement_path, dest / "statement.pdf")

    old_pdfs = {s["pdf"] for s in old_entry.get("solutions", [])}
    kept_pdfs = set()
    new_solutions_meta = []

    for item in solutions:
        method = item["method"].strip()
        if not method:
            continue
        target_pdf = f"solutions/{slugify(method)}.pdf"
        keep_pdf = item.get("keep_pdf")
        file_path = item.get("file_path")
        if keep_pdf:
            kept_pdfs.add(keep_pdf)

        if file_path:
            file_path = Path(file_path).expanduser()
            if not file_path.exists():
                raise ProblemBankError(f"solution PDF not found: {file_path}")
            if new_protected:
                _r2_put_from_file(f"{id}/{target_pdf}", file_path.resolve())
            else:
                shutil.copy(file_path, dest / target_pdf)
            if keep_pdf and not (keep_pdf == target_pdf and old_protected == new_protected):
                _remove_solution_file(id, dest, keep_pdf, old_protected)
        elif keep_pdf:
            if old_protected == new_protected:
                if keep_pdf != target_pdf:
                    if new_protected:
                        with tempfile.TemporaryDirectory() as tmp:
                            tmp_file = Path(tmp) / "sol.pdf"
                            _r2_get_to_file(f"{id}/{keep_pdf}", tmp_file)
                            _r2_put_from_file(f"{id}/{target_pdf}", tmp_file)
                        _r2_delete_best_effort(f"{id}/{keep_pdf}")
                    else:
                        (dest / keep_pdf).rename(dest / target_pdf)
            else:
                if new_protected:
                    _r2_put_from_file(f"{id}/{target_pdf}", (dest / keep_pdf).resolve())
                    (dest / keep_pdf).unlink(missing_ok=True)
                else:
                    _r2_get_to_file(f"{id}/{keep_pdf}", dest / target_pdf)
                    _r2_delete_best_effort(f"{id}/{keep_pdf}")
        else:
            raise ProblemBankError(f"solution '{method}' needs a PDF file")

        new_solutions_meta.append({"method": method, "pdf": target_pdf})

    for pdf in old_pdfs - kept_pdfs:
        _remove_solution_file(id, dest, pdf, old_protected)

    if old_protected and not new_protected:
        _kv_delete_best_effort(id)

    entry = {
        "id": id,
        "subject": subject,
        "topic": topic,
        "tags": tags or [],
        "difficulty": difficulty,
        "type": type,
        "statement_pdf": "statement.pdf",
        "solutions": new_solutions_meta,
        "source": source or "",
        "protected": new_protected,
    }
    other_ids = {p["id"] for p in problems if p["id"] != id}
    errors = validate_entry(entry, schema, other_ids)
    if errors:
        raise ProblemBankError("Entry fails schema validation:\n" + "\n".join(f"- {e}" for e in errors))

    problems[idx] = entry
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
    instead of raising, since 'no keys generated yet' is a normal state.
    Pool shape: {"keys": [{"hash": "<sha256 hex>", "expiresAt": "<ISO8601>"}]}."""
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
        return {"keys": []}
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"keys": []}
    return {"keys": list(parsed.get("keys", []))}


def _kv_put_key_pool(problem_id, pool):
    wrangler(
        "kv", "key", "put", "--binding=PROBLEM_KEYS", problem_id,
        json.dumps(pool), "--remote",
    )


def _kv_delete(problem_id):
    wrangler("kv", "key", "delete", "--binding=PROBLEM_KEYS", problem_id, "--remote", confirm=True)


def _is_live(entry, now):
    return datetime.fromisoformat(entry["expiresAt"]) > now


def generate_keys(problem_id, count, expires_days=30):
    """Generates `count` new one-time-use hex keys for a protected problem's
    solutions, each expiring `expires_days` from now, adds them to the KV
    pool, and returns the new PLAINTEXT keys - the only time they're ever
    visible. Distribute them immediately; they cannot be recovered
    afterward, only revoked early (by removing and re-adding the problem,
    which clears the whole pool)."""
    if count < 1:
        raise ProblemBankError("count must be at least 1")
    if expires_days < 1:
        raise ProblemBankError("expires_days must be at least 1")

    problems = load_problems()
    match = next((p for p in problems if p["id"] == problem_id), None)
    if not match:
        raise ProblemBankError(f"no problem with id '{problem_id}'")
    if not match.get("protected"):
        raise ProblemBankError(f"'{problem_id}' is not a protected problem")

    now = datetime.now(timezone.utc)
    pool = _kv_get_key_pool(problem_id)
    # Drop already-expired entries while we're here rather than letting the
    # pool grow forever.
    live_entries = [e for e in pool["keys"] if _is_live(e, now)]
    existing_hashes = {e["hash"] for e in live_entries}

    expires_at = (now + timedelta(days=expires_days)).isoformat()
    new_keys = []
    while len(new_keys) < count:
        candidate = secrets.token_hex(4)
        h = sha256_hex(candidate)
        if h in existing_hashes:
            continue
        new_keys.append(candidate)
        existing_hashes.add(h)
        live_entries.append({"hash": h, "expiresAt": expires_at})

    _kv_put_key_pool(problem_id, {"keys": live_entries})
    return new_keys


def key_count(problem_id):
    """How many unredeemed, unexpired keys remain for a protected problem."""
    now = datetime.now(timezone.utc)
    return sum(1 for e in _kv_get_key_pool(problem_id)["keys"] if _is_live(e, now))


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
