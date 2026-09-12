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

  # Protected problem (needs a Cloudflare Worker already deployed - see
  # worker/README.md). The statement is still public; only the solutions
  # are gated, by a pool of one-time keys you generate afterward.
  python3 scripts/problems.py add --id quiz3-p2 \\
      --subject Mechanics --topic "Work and Energy" \\
      --difficulty intermediate --type problem \\
      --statement ./statement.pdf --solution "Energy:./sol.pdf" \\
      --protected

  python3 scripts/problems.py generate-keys quiz3-p2 --count 30 --expires-days 30
  python3 scripts/problems.py key-count quiz3-p2

  python3 scripts/problems.py remove mech-projectile-003
  python3 scripts/problems.py list --subject Mechanics
  python3 scripts/problems.py validate

After add/remove, review docs/data/problems.json and commit + push - the
public site (GitHub Pages) picks up changes automatically; protected
problems' KV/R2 data is already live on Cloudflare once 'add'/'remove'/
'generate-keys' finishes.

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
        )
    except bank.ProblemBankError as e:
        print(f"error: {e}")
        sys.exit(1)

    print(f"\nAdded '{args.id}'.", end=" ")
    if args.protected:
        print("Its solutions have no keys yet - run 'generate-keys' to create some.")
    else:
        print()
    print("git add/commit/push docs/ to publish it.")


def cmd_remove(args):
    try:
        bank.remove_problem(args.id)
    except bank.ProblemBankError as e:
        print(f"error: {e}")
        sys.exit(1)
    print(f"Removed '{args.id}'. git add/commit/push docs/ to publish the removal.")


def cmd_generate_keys(args):
    try:
        keys = bank.generate_keys(args.id, args.count, expires_days=args.expires_days)
    except bank.ProblemBankError as e:
        print(f"error: {e}")
        sys.exit(1)
    print(f"Generated {len(keys)} one-time key(s) for '{args.id}', valid for {args.expires_days} day(s):\n")
    for k in keys:
        print(f"  {k}")
    print(f"\nTotal unredeemed, unexpired keys for '{args.id}': {bank.key_count(args.id)}")
    print("These are shown once - distribute them now, they can't be recovered later.")


def cmd_key_count(args):
    try:
        print(bank.key_count(args.id))
    except bank.ProblemBankError as e:
        print(f"error: {e}")
        sys.exit(1)


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
    p_add.add_argument("--protected", action="store_true", help="gate solutions behind one-time keys (statement stays public)")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="remove a problem by id")
    p_remove.add_argument("id")
    p_remove.set_defaults(func=cmd_remove)

    p_genkeys = sub.add_parser("generate-keys", help="generate one-time solution-unlock keys for a protected problem")
    p_genkeys.add_argument("id")
    p_genkeys.add_argument("--count", type=int, default=1)
    p_genkeys.add_argument("--expires-days", type=int, default=30, help="days until these keys expire (default 30)")
    p_genkeys.set_defaults(func=cmd_generate_keys)

    p_keycount = sub.add_parser("key-count", help="print how many unredeemed keys remain for a protected problem")
    p_keycount.add_argument("id")
    p_keycount.set_defaults(func=cmd_key_count)

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
