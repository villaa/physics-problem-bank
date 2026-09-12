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
- **Protected problems**: some problems (e.g. an active quiz) can require an
  access key. That's handled by a small Cloudflare Worker in `worker/` — see
  `worker/README.md` to deploy it once you have a (free) Cloudflare account.

## Managing problems

Use `scripts/problems.py` (Python 3, no extra dependencies) for everything —
adding, removing, listing, and validating problems, public or protected:

```bash
# Public problem
python3 scripts/problems.py add --id mech-projectile-003 \
    --subject Mechanics --topic "Projectile Motion" \
    --difficulty intro --type problem \
    --statement ~/Desktop/problem.pdf \
    --solution "Kinematics:~/Desktop/solution.pdf" \
    --tags projectile,kinematics --source Original

# Protected problem (needs the Cloudflare Worker deployed - see worker/README.md)
python3 scripts/problems.py add --id quiz3-p2 \
    --subject Mechanics --topic "Work and Energy" \
    --difficulty intermediate --type problem \
    --statement ./statement.pdf --solution "Energy:./sol.pdf" \
    --protected --key "fall2026-quiz3"

python3 scripts/problems.py remove mech-projectile-003
python3 scripts/problems.py list --subject Mechanics
python3 scripts/problems.py validate
```

`add` copies the PDF(s) into place (or uploads them to the private R2
bucket, for protected problems) and appends the metadata entry;
`remove` deletes both the metadata and the files/R2-KV data together.
After `add`/`remove`, commit and push `docs/` — GitHub Pages redeploys
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

Then open `http://localhost:8000`.
