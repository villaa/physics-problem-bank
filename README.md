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

## Adding a public problem

1. Pick an id, e.g. `mech-projectile-003`.
2. Put its PDFs under `docs/problems/mech-projectile-003/`:
   - `statement.pdf` (the problem + any diagram)
   - `solutions/<method-name>.pdf` for each solution approach
3. Add an entry to `docs/data/problems.json`:

```json
{
  "id": "mech-projectile-003",
  "subject": "Mechanics",
  "topic": "Projectile Motion",
  "tags": ["projectile", "kinematics"],
  "difficulty": "intro",
  "type": "problem",
  "statement_pdf": "problems/mech-projectile-003/statement.pdf",
  "solutions": [
    { "method": "Kinematic equations", "pdf": "problems/mech-projectile-003/solutions/kinematics.pdf" }
  ],
  "source": "Original",
  "protected": false
}
```

4. Commit and push — GitHub Pages redeploys automatically.

## Adding a protected problem

See `worker/README.md`.

## Local preview

```bash
cd docs
python3 -m http.server 8000
```

Then open `http://localhost:8000`.
