#!/usr/bin/env python3
"""Local web UI for managing the physics problem bank.

Run:
    python3 admin/server.py

Opens http://127.0.0.1:5151 in your browser. Binds to localhost only -
not reachable from other machines, and not meant to be. This is a thin
form-based front end over the same scripts/problem_bank.py logic used by
scripts/problems.py, so behavior (schema validation, Cloudflare
upload/delete for protected problems, etc.) is identical either way.
"""
import secrets
import subprocess
import sys
import tempfile
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import problem_bank as bank  # noqa: E402
from flask import Flask, flash, redirect, render_template, request, url_for  # noqa: E402

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

DIFFICULTIES = ["intro", "intermediate", "advanced"]
TYPES = ["problem", "conceptual", "derivation"]


def run_git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )


@app.route("/")
def index():
    problems = bank.load_problems()
    subjects = sorted({p["subject"] for p in problems})
    status = run_git("status", "--porcelain", "--", "docs")
    unpublished = bool(status.stdout.strip())
    key_counts = {p["id"]: bank.key_count(p["id"]) for p in problems if p.get("protected")}
    return render_template(
        "index.html",
        problems=problems,
        subjects=subjects,
        difficulties=DIFFICULTIES,
        types=TYPES,
        unpublished=unpublished,
        references=bank.load_references(),
        key_counts=key_counts,
    )


@app.route("/add", methods=["POST"])
def add():
    form = request.form
    methods = form.getlist("solution_method")
    files = request.files.getlist("solution_file")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        statement_file = request.files.get("statement_file")
        if not statement_file or not statement_file.filename:
            flash("A statement PDF is required.", "error")
            return redirect(url_for("index"))
        statement_path = tmp_path / "statement.pdf"
        statement_file.save(statement_path)

        solutions = []
        for method, f in zip(methods, files):
            if not method.strip() or not f or not f.filename:
                continue
            sol_path = tmp_path / f"solution-{bank.slugify(method)}.pdf"
            f.save(sol_path)
            solutions.append((method.strip(), sol_path))

        protected = form.get("protected") == "on"
        tags = [t.strip() for t in form.get("tags", "").split(",") if t.strip()]

        try:
            bank.add_problem(
                id=form["id"].strip(),
                subject=form["subject"].strip(),
                topic=form["topic"].strip(),
                difficulty=form["difficulty"],
                type=form["type"],
                statement_path=statement_path,
                solutions=solutions,
                tags=tags,
                source=form.get("source", "").strip(),
                protected=protected,
            )
        except bank.ProblemBankError as e:
            flash(str(e), "error")
            return redirect(url_for("index"))
        except KeyError as e:
            flash(f"Missing field: {e}", "error")
            return redirect(url_for("index"))

    msg = f"Added '{form['id'].strip()}'."
    if protected:
        msg += " Its solutions have no keys yet - use 'Generate keys' below."
    msg += " Click 'Publish to GitHub' below to make it live."
    flash(msg, "success")
    return redirect(url_for("index"))


@app.route("/remove/<problem_id>", methods=["POST"])
def remove(problem_id):
    try:
        bank.remove_problem(problem_id)
        flash(f"Removed '{problem_id}'. Click 'Publish to GitHub' below to make the removal live.", "success")
    except bank.ProblemBankError as e:
        flash(str(e), "error")
    return redirect(url_for("index"))


@app.route("/keys/generate/<problem_id>", methods=["POST"])
def generate_keys(problem_id):
    try:
        count = int(request.form.get("count", "1"))
        expires_days = int(request.form.get("expires_days", "30"))
    except ValueError:
        flash("Key count and expiry must be numbers.", "error")
        return redirect(url_for("index"))

    try:
        keys = bank.generate_keys(problem_id, count, expires_days=expires_days)
    except bank.ProblemBankError as e:
        flash(str(e), "error")
        return redirect(url_for("index"))

    flash(
        f"Generated {len(keys)} key(s) for '{problem_id}', valid {expires_days} day(s) - shown once, copy them now:\n"
        + "\n".join(keys)
        + f"\n\nTotal unredeemed, unexpired keys for '{problem_id}': {bank.key_count(problem_id)}",
        "success",
    )
    return redirect(url_for("index"))


@app.route("/publish", methods=["POST"])
def publish():
    status = run_git("status", "--porcelain", "--", "docs")
    if status.returncode != 0:
        flash(f"git status failed: {status.stderr}", "error")
        return redirect(url_for("index"))
    if not status.stdout.strip():
        flash("Nothing to publish - docs/ has no changes.", "success")
        return redirect(url_for("index"))

    add = run_git("add", "docs")
    if add.returncode != 0:
        flash(f"git add failed: {add.stderr}", "error")
        return redirect(url_for("index"))

    message = f"Update problem bank via admin UI ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    commit = run_git("commit", "-m", message)
    if commit.returncode != 0:
        flash(f"git commit failed: {commit.stderr or commit.stdout}", "error")
        return redirect(url_for("index"))

    push = run_git("push")
    if push.returncode != 0:
        flash(
            f"Committed locally, but git push failed: {push.stderr}\n"
            "Push manually once the issue is fixed.",
            "error",
        )
        return redirect(url_for("index"))

    flash("Published to GitHub - the live site will update shortly.", "success")
    return redirect(url_for("index"))


@app.route("/references/add", methods=["POST"])
def add_reference():
    try:
        bank.add_reference(request.form.get("label", ""), request.form.get("bibtex", ""))
        flash("Reference added.", "success")
    except bank.ProblemBankError as e:
        flash(str(e), "error")
    return redirect(url_for("index"))


@app.route("/references/remove", methods=["POST"])
def remove_reference():
    try:
        bank.remove_reference(request.form.get("label", ""))
        flash("Reference removed.", "success")
    except bank.ProblemBankError as e:
        flash(str(e), "error")
    return redirect(url_for("index"))


@app.route("/validate", methods=["POST"])
def validate():
    results = bank.validate_all()
    if not results:
        flash("All problems valid.", "success")
    else:
        for pid, errors in results.items():
            flash(f"{pid}: " + "; ".join(errors), "error")
    return redirect(url_for("index"))


def open_browser():
    webbrowser.open("http://127.0.0.1:5151")


if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    app.run(host="127.0.0.1", port=5151, debug=False)
