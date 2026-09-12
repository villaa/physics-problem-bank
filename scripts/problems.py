#!/usr/bin/env python3
"""Manage the physics problem bank: add, remove, list, and validate entries.

Examples:
  # Public problem
  python3 scripts/problems.py add --id mech-projectile-003 \\
      --subject Mechanics --topic "Projectile Motion" \\
      --difficulty intro --type problem \\
      --statement ~/Desktop/problem.pdf \\
      --solution "Kinematics:~/Desktop/solution.pdf" \\
      --tags projectile,kinematics --source Original

  # Protected problem (needs a Cloudflare Worker already deployed - see worker/README.md)
  python3 scripts/problems.py add --id quiz3-p2 \\
      --subject Mechanics --topic "Work and Energy" \\
      --difficulty intermediate --type problem \\
      --statement ./statement.pdf --solution "Energy:./sol.pdf" \\
      --protected --key "fall2026-quiz3"

  python3 scripts/problems.py remove mech-projectile-003
  python3 scripts/problems.py list --subject Mechanics
  python3 scripts/problems.py validate

After add/remove, review docs/data/problems.json and commit + push - the
public site (GitHub Pages) picks up changes automatically; protected
problems' KV/R2 data is already live on Cloudflare once 'add'/'remove'
finishes.
"""
import argparse
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
        print("error: 'npx' not found on PATH (needed to run wrangler)")
        sys.exit(1)
    cmd = [npx, "wrangler", *args]
    print("+", " ".join(cmd))
    subprocess.run(
        cmd,
        cwd=WORKER_DIR,
        input="y\n" if confirm else None,
        text=True,
        check=True,
    )


def sha256_hex(s):
    return hashlib.sha256(s.encode()).hexdigest()


def cmd_add(args):
    problems = load_problems()
    schema = load_schema()

    if any(p["id"] == args.id for p in problems):
        print(f"error: id '{args.id}' already exists. Remove it first or pick a new id.")
        sys.exit(1)

    solutions_meta = []
    for sol in args.solution or []:
        method, sep, path = sol.partition(":")
        if not sep:
            print(f"error: --solution must be 'method:path', got '{sol}'")
            sys.exit(1)
        solutions_meta.append((method, Path(path).expanduser()))

    entry = {
        "id": args.id,
        "subject": args.subject,
        "topic": args.topic,
        "tags": [t.strip() for t in args.tags.split(",")] if args.tags else [],
        "difficulty": args.difficulty,
        "type": args.type,
        "statement_pdf": "statement.pdf",
        "solutions": [
            {"method": m, "pdf": f"solutions/{slugify(m)}.pdf"} for m, _ in solutions_meta
        ],
        "source": args.source or "",
        "protected": bool(args.protected),
    }

    errors = validate_entry(entry, schema, {p["id"] for p in problems})
    if errors:
        print("error: entry fails schema validation:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    statement_src = Path(args.statement).expanduser()
    if not statement_src.exists():
        print(f"error: statement PDF not found: {statement_src}")
        sys.exit(1)
    for _, path in solutions_meta:
        if not path.exists():
            print(f"error: solution PDF not found: {path}")
            sys.exit(1)

    if args.protected:
        if not args.key:
            print("error: --protected requires --key")
            sys.exit(1)
        key_hash = sha256_hex(args.key)
        wrangler(
            "kv", "key", "put", "--binding=PROBLEM_KEYS", args.id,
            json.dumps({"keyHash": key_hash}), "--remote",
        )
        wrangler(
            "r2", "object", "put",
            f"{R2_BUCKET}/{args.id}/statement.pdf",
            f"--file={statement_src.resolve()}", "--remote",
        )
        for method, path in solutions_meta:
            wrangler(
                "r2", "object", "put",
                f"{R2_BUCKET}/{args.id}/solutions/{slugify(method)}.pdf",
                f"--file={path.resolve()}", "--remote",
            )
        print(f"\nAccess key for '{args.id}': {args.key}  (share with students)")
    else:
        dest = PROBLEMS_DIR / args.id
        (dest / "solutions").mkdir(parents=True, exist_ok=True)
        shutil.copy(statement_src, dest / "statement.pdf")
        for method, path in solutions_meta:
            shutil.copy(path, dest / "solutions" / f"{slugify(method)}.pdf")

    problems.append(entry)
    save_problems(problems)
    print(f"\nAdded '{args.id}'. git add/commit/push docs/ to publish it.")


def cmd_remove(args):
    problems = load_problems()
    match = next((p for p in problems if p["id"] == args.id), None)
    if not match:
        print(f"error: no problem with id '{args.id}'")
        sys.exit(1)

    if match.get("protected"):
        wrangler("kv", "key", "delete", "--binding=PROBLEM_KEYS", args.id, "--remote", confirm=True)
        wrangler("r2", "object", "delete", f"{R2_BUCKET}/{args.id}/statement.pdf", "--remote")
        for sol in match.get("solutions", []):
            wrangler("r2", "object", "delete", f"{R2_BUCKET}/{args.id}/{sol['pdf']}", "--remote")
    else:
        dest = PROBLEMS_DIR / args.id
        if dest.exists():
            shutil.rmtree(dest)

    problems = [p for p in problems if p["id"] != args.id]
    save_problems(problems)
    print(f"Removed '{args.id}'. git add/commit/push docs/ to publish the removal.")


def cmd_validate(args):
    problems = load_problems()
    schema = load_schema()
    seen = set()
    ok = True
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
            ok = False
            print(f"[{pid}]")
            for e in errors:
                print(f"  - {e}")

    if ok:
        print(f"OK - {len(problems)} problem(s) valid.")
    sys.exit(0 if ok else 1)


def cmd_list(args):
    problems = load_problems()
    for p in problems:
        if args.subject and p.get("subject") != args.subject:
            continue
        if args.protected and not p.get("protected"):
            continue
        lock = "[locked] " if p.get("protected") else ""
        print(f"{p['id']:30s} {lock}{p.get('subject', ''):15s} {p.get('topic', '')} ({p.get('difficulty', '')})")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add a new problem")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--subject", required=True)
    p_add.add_argument("--topic", required=True)
    p_add.add_argument("--difficulty", required=True, choices=["intro", "intermediate", "advanced"])
    p_add.add_argument("--type", required=True, choices=["problem", "conceptual", "derivation"])
    p_add.add_argument("--statement", required=True, help="path to statement PDF")
    p_add.add_argument("--solution", action="append", help="method:path, repeatable")
    p_add.add_argument("--tags", help="comma-separated")
    p_add.add_argument("--source")
    p_add.add_argument("--protected", action="store_true")
    p_add.add_argument("--key", help="plaintext access key (required with --protected)")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="remove a problem by id")
    p_remove.add_argument("id")
    p_remove.set_defaults(func=cmd_remove)

    p_validate = sub.add_parser("validate", help="validate problems.json against schema.json")
    p_validate.set_defaults(func=cmd_validate)

    p_list = sub.add_parser("list", help="list problems")
    p_list.add_argument("--subject")
    p_list.add_argument("--protected", action="store_true")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
