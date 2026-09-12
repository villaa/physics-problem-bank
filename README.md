# Physics Problem Bank

A searchable, web-based repository of physics problems and solutions.

- **Public site**: static HTML/JS in `docs/`, hosted free on GitHub Pages.
  Problems are metadata-only in `docs/data/problems.json`; the actual
  statements and diagrams are PDFs (already-typeset LaTeX exports work great)
  under `docs/problems/<id>/`.
- **Search/filter**: by subject, topic, tags, and difficulty (metadata only —
  not full-text search inside the PDFs).
- **Worksheet builder**: pick several problems and it merges their statement
  PDFs into one printable packet client-side (via pdf-lib), plus a separate
  answer-key packet from the solutions.
- **Protected solutions**: a problem's statement is always public; its
  solutions can instead require a one-time key (generate a batch, hand one
  per student — each works exactly once, then it's consumed). Handled by a
  small Cloudflare Worker in `worker/` — see `worker/README.md` to deploy it
  once you have a (free) Cloudflare account.

## Setup

New machine? See `SETUP.md` for Windows/macOS/Linux install steps
(Git, Python, Node.js, GitHub CLI) through to a running admin UI.

## Managing problems

Two ways to manage content — both call the same underlying logic
(`scripts/problem_bank.py`), so pick whichever you prefer:

- **Web form** (`admin/`) — a local browser UI for adding/removing problems
  without typing commands. See `admin/README.md`.
- **CLI** (`scripts/problems.py`, Python 3, no extra dependencies) — for
  scripting or quick one-liners:

```bash
# Public problem
python3 scripts/problems.py add --id mech-projectile-003 \
    --subject Mechanics --topic "Projectile Motion" \
    --difficulty intro --type problem \
    --statement ~/Desktop/problem.pdf \
    --solution "Kinematics:~/Desktop/solution.pdf" \
    --tags projectile,kinematics --source Original

# Protected problem (needs the Cloudflare Worker deployed - see worker/README.md).
# The statement is still public - only its solutions get gated, by one-time
# keys you generate afterward (no key needed here).
python3 scripts/problems.py add --id quiz3-p2 \
    --subject Mechanics --topic "Work and Energy" \
    --difficulty intermediate --type problem \
    --statement ./statement.pdf --solution "Energy:./sol.pdf" \
    --protected

python3 scripts/problems.py generate-keys quiz3-p2 --count 30
python3 scripts/problems.py key-count quiz3-p2

python3 scripts/problems.py remove mech-projectile-003
python3 scripts/problems.py list --subject Mechanics
python3 scripts/problems.py validate
```

`add` copies the statement PDF into place always, and copies solution PDFs
too unless the problem is protected (those upload to the private R2 bucket
instead) - then appends the metadata entry. `remove` deletes the metadata,
the local files, and any R2/KV data together. After `add`/`remove`/
`generate-keys`, commit and push `docs/` — GitHub Pages redeploys
automatically; protected problems' Cloudflare data is already live as
soon as the command finishes.

### Refining the schema

`docs/data/problems.json` entries are checked against
`docs/data/schema.json` — a plain-JSON description of each field's type and
allowed values. To add, remove, or restrict a field, edit `schema.json`,
then run `python3 scripts/problems.py validate` to see which existing
entries need updating to match.

## Local preview

```bash
cd docs
python3 -m http.server 8000
```

Then open `http://localhost:8000`. Note: the Cloudflare Worker only allows
requests from the real GitHub Pages origin (CORS), so unlocking a
protected problem's solutions won't work from localhost — everything else
(browsing, search, worksheet builder, public problems) works fine locally.
