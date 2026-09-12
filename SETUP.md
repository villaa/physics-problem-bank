# Setup guide (Windows / macOS / Linux)

Getting a fresh machine from "nothing installed" to a running admin UI.
For what the tools actually do once installed, see the root `README.md`,
`admin/README.md`, and `worker/README.md`.

## 1. Prerequisites

You need, regardless of OS:

- **Git**
- **Python 3.9+**
- **GitHub CLI** (`gh`) — used for repo access and the "Publish to GitHub" button
- **Node.js 18+** (only if you'll deploy/manage the Cloudflare Worker for protected problems)

### Windows

Using [winget](https://learn.microsoft.com/en-us/windows/package-manager/winget/) (built into modern Windows):

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id GitHub.cli -e
winget install --id OpenJS.NodeJS.LTS -e
```

**Important**: after installing, close and reopen your terminal (PATH changes
only take effect in new terminal sessions, not ones already open).

### macOS

Using [Homebrew](https://brew.sh/):

```bash
brew install git python node gh
```

### Linux (Debian/Ubuntu example)

```bash
sudo apt update
sudo apt install git python3 python3-venv nodejs npm
```

`gh` is packaged directly on recent Ubuntu/Debian (`sudo apt install gh`); if
that's not available on your version, see GitHub's official install steps at
https://github.com/cli/cli/blob/trunk/docs/install_linux.md. Other distros:
`sudo dnf install gh` (Fedora), `sudo pacman -S github-cli` (Arch), or
`brew install gh` (Homebrew also works on Linux).

## 2. Clone the repo

```bash
git clone https://github.com/villaa/physics-problem-bank.git
cd physics-problem-bank
```

## 3. Authenticate GitHub CLI (once per machine)

```bash
gh auth login
```

Follow the prompts (opens a browser for a one-time device code). This is
what lets the admin UI's "Publish to GitHub" button push on your behalf,
via your normal `git`/`gh` credentials.

## 4. Set up the admin web UI

**Windows:**

```powershell
cd admin
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run it (from the repo root, in a new terminal or after `cd ..`):

```powershell
admin\.venv\Scripts\python.exe admin\server.py
```

**macOS/Linux:**

```bash
cd admin
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Run it (from the repo root):

```bash
admin/.venv/bin/python admin/server.py
```

Either way, this opens `http://127.0.0.1:5151` in your browser
automatically. See `admin/README.md` for what the UI does.

## 5. (Optional) Set up the Cloudflare Worker for protected problems

Only needed if you want key-gated problems. Requires a free Cloudflare
account. Full steps, identical across OSes since they're all `npm`/`npx`
based, are in `worker/README.md`:

```bash
cd worker
npm install
npx wrangler login
npx wrangler kv namespace create PROBLEM_KEYS   # paste the id into wrangler.toml
npx wrangler r2 bucket create physics-problem-bank-protected
npx wrangler deploy
```

Paste the deployed Worker URL into `docs/js/config.js` as `WORKER_URL`.

## Troubleshooting

- **"gh"/"npx"/"python" not recognized right after installing** — close and
  reopen your terminal. Installers update the system PATH, but any terminal
  already open (including this one, if you're running Claude Code) keeps
  its old copy of PATH until restarted.
- **R2 bucket creation fails with error code 10042** — Cloudflare requires
  enabling R2 once from the dashboard (Dashboard → R2) before the API can
  create buckets. It may ask for a payment method even though the free tier
  (10GB storage, 1M/10M ops per month) covers this project.
- **"You need to register a workers.dev subdomain"** — follow the link
  `wrangler deploy` prints, pick a subdomain once per Cloudflare account,
  then run `npx wrangler deploy` again.
