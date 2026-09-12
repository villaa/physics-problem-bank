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

Prefer a form over flags? Run 'python3 admin/server.py' instead - a local
web UI for the same operations (see admin/README.md).
"""
import argparse
import sys
from pathlib import Path

import problem_bank as bank


def cmd_add(args):
    solutions = []
    for sol in args.solution or []:
        method, sep, path = sol.partition(":")
        if not sep:
            print(f"error: --solution must be 'method:path', got '{sol}'")
            sys.exit(1)
        solutions.append((method, Path(path).expanduser()))

    try:
        bank.add_problem(
            id=args.id,
            subject=args.subject,
            topic=args.topic,
            difficulty=args.difficulty,
            type=args.type,
            statement_path=args.statement,
            solutions=solutions,
            tags=[t.strip() for t in args.tags.split(",")] if args.tags else [],
            source=args.source or "",
            protected=args.protected,
            key=args.key,
        )
    except bank.ProblemBankError as e:
        print(f"error: {e}")
        sys.exit(1)

    if args.protected:
        print(f"\nAccess key for '{args.id}': {args.key}  (share with students)")
    print(f"\nAdded '{args.id}'. git add/commit/push docs/ to publish it.")


def cmd_remove(args):
    try:
        bank.remove_problem(args.id)
    except bank.ProblemBankError as e:
        print(f"error: {e}")
        sys.exit(1)
    print(f"Removed '{args.id}'. git add/commit/push docs/ to publish the removal.")


def cmd_validate(args):
    results = bank.validate_all()
    total = len(bank.load_problems())
    if not results:
        print(f"OK - {total} problem(s) valid.")
        sys.exit(0)
    for pid, errors in results.items():
        print(f"[{pid}]")
        for e in errors:
            print(f"  - {e}")
    sys.exit(1)


def cmd_list(args):
    for p in bank.list_problems(subject=args.subject, protected_only=args.protected):
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
