# Cloudflare Worker — one-time key access for solutions

This Worker guards protected problems' **solutions** with a pool of
one-time-use keys — generate a batch, hand one to each student, and each key
works exactly once. A problem's **statement is always public** (served
directly by GitHub Pages from `docs/problems/`), protected or not; only its
solution PDFs ever require a key, and only if you mark the problem
`protected: true`.

## One-time setup (once you have a Cloudflare account)

```bash
cd worker
npm install
npx wrangler login          # opens a browser to authenticate

npx wrangler kv namespace create PROBLEM_KEYS
# copy the returned "id" into wrangler.toml's [[kv_namespaces]] block

npx wrangler r2 bucket create physics-problem-bank-protected
# (Cloudflare may first require enabling R2 once from the dashboard)

npx wrangler deploy
```

`wrangler deploy` prints the Worker's URL. If your account has no
`workers.dev` subdomain yet, register one from the dashboard link it shows,
then run `npx wrangler deploy` again. Paste the final URL into
`docs/js/config.js` as `WORKER_URL`.

## Adding a protected problem and generating keys

Use `scripts/problems.py` from the repo root (not a Worker-specific script —
it handles public and protected problems together and keeps
`docs/data/problems.json` in sync):

```bash
# The statement is public even though the problem is "protected" - only
# its solutions get gated. No key is needed at add time.
python3 scripts/problems.py add --id quiz3-p2 \
    --subject Mechanics --topic "Work and Energy" \
    --difficulty intermediate --type problem \
    --statement ./statement.pdf --solution "Energy:./sol.pdf" \
    --protected

# Generate a batch of one-time keys (e.g. one per student) whenever you're
# ready to hand them out. Each run adds to the pool; existing keys are
# unaffected.
python3 scripts/problems.py generate-keys quiz3-p2 --count 30

# How many keys are still unredeemed:
python3 scripts/problems.py key-count quiz3-p2

python3 scripts/problems.py remove quiz3-p2
```

The same is available from the admin web UI: a "Generate" control per
protected problem row, and the generated keys are shown once in a flash
message right after.

**Keys are shown exactly once, at generation time** — only their SHA-256
hashes are ever stored (in KV), so there's no way to look a key back up
later. Copy/distribute them immediately. To revoke every outstanding key at
once, `remove` the problem and `add` it again (this clears the whole pool);
there's currently no way to revoke a single key without regenerating all of
them.

## How it works

- Each protected problem has a KV entry (`PROBLEM_KEYS`, keyed by problem
  id) holding `{"keyHashes": ["<sha256 hex>", ...]}` — a pool of unredeemed
  keys. `generate-keys` appends new hashes to this pool.
- When a student enters a key, `docs/js/app.js` calls
  `POST /problem/:id/redeem` with `{key, files}` (files = every solution PDF
  path for that problem, from `problems.json`).
- The Worker hashes the submitted key, and if it's in the pool: removes it
  (one-time use enforced server-side, not just client-side) *then* returns
  every requested solution file, base64-encoded, in that single response —
  so one key unlocks all of a problem's solution methods at once, not just
  the first one you happen to click.
- Wrong or already-used key → `403`. Without the correct key, no solution
  bytes ever leave R2.
- This relies on Cloudflare KV's read-modify-write, not a real transaction —
  two students submitting the same key in the same instant could both
  succeed in a narrow race window. Not a concern at classroom scale (KV
  operations are far faster than two people typing the same code
  simultaneously), but worth knowing if this ever needs to scale up.
