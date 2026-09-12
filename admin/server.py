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
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import problem_bank as bank  # noqa: E402
from flask import Flask, flash, redirect, render_template, request, url_for  # noqa: E402

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

DIFFICULTIES = ["intro", "intermediate", "advanced"]
TYPES = ["problem", "conceptual", "derivation"]


@app.route("/")
def index():
    problems = bank.load_problems()
    subjects = sorted({p["subject"] for p in problems})
    return render_template(
        "index.html",
        problems=problems,
        subjects=subjects,
        difficulties=DIFFICULTIES,
        types=TYPES,
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
                key=form.get("key", "").strip() or None,
            )
        except bank.ProblemBankError as e:
            flash(str(e), "error")
            return redirect(url_for("index"))
        except KeyError as e:
            flash(f"Missing field: {e}", "error")
            return redirect(url_for("index"))

    msg = f"Added '{form['id'].strip()}'."
    if protected:
        msg += f" Access key: {form.get('key', '').strip()} (share with students)."
    msg += " Remember to git add/commit/push docs/ to publish it."
    flash(msg, "success")
    return redirect(url_for("index"))


@app.route("/remove/<problem_id>", methods=["POST"])
def remove(problem_id):
    try:
        bank.remove_problem(problem_id)
        flash(f"Removed '{problem_id}'. git add/commit/push docs/ to publish the removal.", "success")
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
