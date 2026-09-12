# Admin web UI

A local web form for adding/removing problems, instead of typing
`scripts/problems.py` flags by hand. Same underlying logic either way
(`scripts/problem_bank.py`) - the CLI and this UI stay in sync automatically.

## Setup (one time)

```bash
cd admin
python3 -m venv .venv

# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS/Linux
.venv/bin/python -m pip install -r requirements.txt
```

## Run

```bash
# Windows
admin\.venv\Scripts\python.exe admin\server.py
# macOS/Linux
admin/.venv/bin/python admin/server.py
```

Opens `http://127.0.0.1:5151` in your browser automatically. The server only
binds to `127.0.0.1` (localhost) - nobody else on your network can reach it.

## What it does

- **Add a problem**: fill in the metadata, attach a statement PDF and any
  number of solution PDFs (each with a method name), optionally check
  "Protect this problem" and set an access key. Submitting runs the exact
  same code path as `scripts/problems.py add` - PDFs get copied into
  `docs/problems/<id>/`, or (if protected) hashed/uploaded to Cloudflare
  KV + R2.
- **Reusable references**: save a citation once (e.g. a textbook edition),
  optionally with its BibTeX entry, and it appears in the Reference dropdown
  when adding future problems. Section and Page are separate optional fields
  per problem; all three combine into the Source box automatically (still
  editable by hand afterward). Stored in `admin/references.json` as
  `{label, bibtex}` entries, independent of `docs/data/problems.json`.
- **Remove**: a button per row in the existing-problems table.
- **Validate all**: checks every entry against `docs/data/schema.json` and
  confirms referenced PDFs exist, same as `scripts/problems.py validate`.

After adding or removing, you still need to `git add/commit/push docs/` to
publish the change to the live site (protected problems' Cloudflare data is
already live as soon as the form submits).
