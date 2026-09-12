# Cloudflare Worker — protected problem access

This Worker guards protected problems: a viewer must supply the correct
access key before a solution or statement PDF is ever sent to the browser.
Public (non-protected) problems don't touch this at all — they're served
directly by GitHub Pages from `docs/problems/`.

## One-time setup (once you have a Cloudflare account)

```bash
cd worker
npm install
npx wrangler login          # opens a browser to authenticate

npx wrangler kv namespace create PROBLEM_KEYS
# copy the returned "id" into wrangler.toml's [[kv_namespaces]] block

npx wrangler r2 bucket create physics-problem-bank-protected

npx wrangler deploy
```

`wrangler deploy` prints the Worker's URL
(`https://physics-problem-bank-worker.<your-subdomain>.workers.dev`).
Paste that into `docs/js/config.js` as `WORKER_URL`.

## Adding a protected problem

```bash
cd worker
./scripts/add-protected-problem.sh <problem-id> <plaintext-key> <statement-pdf> \
    [solution-name:solution-pdf ...]
```

This hashes the key (SHA-256, never stored in plaintext), uploads the PDF(s)
to the private R2 bucket, and prints the key to hand out to students. Then
add a matching entry to `docs/data/problems.json` with `"protected": true`.

## How it works

- `docs/js/app.js` shows a key-entry box for any problem marked
  `protected: true` and calls the Worker at
  `GET /problem/:id/:file?key=...`.
- The Worker hashes the submitted key and compares it to the stored hash in
  KV. Only on a match does it stream the actual PDF bytes from R2.
- Without the correct key, the PDF bytes never leave R2 — inspecting network
  traffic reveals nothing, unlike a "guess the URL" scheme.
