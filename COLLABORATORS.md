# Adding a collaborator

Each person runs their own local Admin UI against their own credentials -
there's no shared server or login inside the app itself (see "Security
model" below). Give someone access in two independent steps, depending on
what they need to do.

## 1. GitHub access (required for everyone)

They need push access to publish changes (the "Publish to GitHub" button,
or `git push` from the CLI).

**Via the GitHub UI:** repo → Settings → Collaborators and teams → Add
people → enter their GitHub username → pick **Write**.

**Via the CLI**, equivalent:

```bash
gh api repos/villaa/physics-problem-bank/collaborators/<their-username> \
    -X PUT -f permission=push
```

They'll get a GitHub notification/email to accept the invite. Once
accepted, they follow `SETUP.md` end to end - clone the repo, run
`gh auth login` under *their own* GitHub account, and start their own
local Admin UI. Their commits will show up under their own name.

Note: there's no branch protection on `master`, so their pushes go live
immediately with no review step - same as yours do.

## 2. Cloudflare access (only if they'll manage protected problems)

Needed only for generating/revoking keys, or editing a problem that's
`protected` (those touch the R2 bucket and the KV key pool). Skip this if
they'll only work with public problems.

They do **not** need their own Cloudflare account - a token is a
credential on *your* account, not a login. Don't share your Cloudflare
login itself, though; instead create them a scoped API token:

1. Cloudflare dashboard → your profile icon → **API Tokens** → **Create
   Token** → **Create Custom Token**.
2. Permissions: **Workers R2 Storage: Edit** and **Workers KV Storage:
   Edit**, scoped to your account.
3. Send them the generated token (once - Cloudflare won't show it again).

On their machine, instead of `npx wrangler login` (which would be a full
OAuth login to *your* account), they set:

```bash
export CLOUDFLARE_API_TOKEN=<the token you gave them>   # macOS/Linux
$env:CLOUDFLARE_API_TOKEN = "<the token you gave them>" # Windows PowerShell
```

before running `problems.py`/the Admin UI. This scopes them to exactly
R2 + KV, nothing else on the account (no billing, no other zones/workers).

## Revoking access

- GitHub: repo → Settings → Collaborators and teams → remove them.
- Cloudflare: dashboard → API Tokens → **Roll** or **Delete** the token
  you gave them.

## Security model (context)

The Admin UI itself has no login of its own - it only binds to
`127.0.0.1`, so it's reachable only from processes already on that
machine. The real gates are (a) who has code-execution access to a given
machine, and (b) whose GitHub/Cloudflare credentials are cached there.
Adding a collaborator means trusting them with real push/Cloudflare
access, not with some separate "admin app password" - there isn't one.
