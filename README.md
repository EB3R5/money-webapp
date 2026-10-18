# Passbook

Passbook is a personal finance web app over a SQLite data directory. A Django app serves an editable
Ledger, Accounts, Inventory, Software, Kits, Balances, P&L, Balance Sheet, Dashboard, and a Planning
section (a monthly journal over the ledger's figures, a Notebook, a Planner, typed Expected flows,
and a Year plan of planned spend pulled from future-purchases on demand); transactions and
balances arrive from the SimpleFIN Bridge (optional) and from what you type.

The design is inspired by passbooks, the small bank booklets in which every deposit and
withdrawal was entered by hand in columns with the balance carried forward. Pale ledger-green
paper, one column rule down the page, serif headings over tabular figures, red ink only for
money going out and bank green for money coming in.

Architecture decisions are recorded in [`docs/adr/`](docs/adr/); the domain vocabulary
lives in [`CONTEXT.md`](CONTEXT.md).
Assets, trust boundaries, the threat model, and the compromise runbook are in
[`docs/SECURITY.md`](docs/SECURITY.md); what the host owns in [`docs/deployment.md`](docs/deployment.md);
backups in [`docs/backups.md`](docs/backups.md).

## Categorization

Transactions get a Category two ways, kept apart on purpose. **Rules** (`/categorization`,
Rules tab) are first-match-wins substring/amount conditions with an explicit order and an
enabled flag; the tab shows what each Rule matches, wins, and would write, and a
"Test a transaction" form. The **ML model** (ML model tab) only ever suggests: its top pick
is stored as `Pred:Category` / `Pred:Conf`, never as Category, and it can be retrained from
the categorized ledger. On the Ledger, "Apply rules" and "ML suggest" run each in batch, and
clicking a row shows the Rule hit and the ML picks without writing anything until a chip is
clicked. A fresh install has no model: the model tab counts the categorized transactions a
retrain needs (ten), the Ledger's ML suggest button is disabled until one exists, and the first
retrain switches both on. See `CONTEXT.md` (Rule, Rule engine, ML model, ML suggestion, Rule apply).

## Run

Needs Python 3.12+. No external service.

```bash
cp .env.example .env            # set SESSION_SECRET (the app refuses to start without it)
python -m venv .venv && ./.venv/bin/pip install -e ".[desktop,dev]"
./.venv/bin/python manage.py init_store && ./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py runserver 8012
./.venv/bin/python manage.py run_jobs         # optional: the feed's scheduled runs, in a second terminal
```

Or with Docker: `cp .env.example .env`, set `SESSION_SECRET`, then `docker compose up -d --build`
(the web service and the jobs process from one image, on <http://127.0.0.1:8012/>; `./data`
is the data directory).

Then open <http://localhost:8012/>: with no account yet, the login page is a one-time setup
form where you choose the admin's username and password. (A headless deployment sets
`DEFAULT_USER` / `DEFAULT_PASSWORD` instead and `manage.py bootstrap_admin` — the container's
entrypoint runs it — creates that admin, who must change the password at the first sign-in.)
A second person joins through an **invitation link**: mint one on **Settings → Users** (or with
`manage.py invite`), shown once, a week's expiry, one use; the register page it opens makes them a
member. The same page lists the members, mints reset links, deactivates or promotes. Someone locked out gets a one-time
**reset link** the same way (`manage.py reset_link <user>`); the app sends no email.
A script or an agent uses a per-user **API token** instead of a browser session: mint one on `/account`
(or `manage.py api_token <user> --name ...`), send it as `Authorization: Bearer <token>`; the software
import endpoint is the first thing built for it. `GET /healthz` returns `{"ok": true}`. The data directory
(`DATA_DIR`, default `./data`) is created on first start, with **starter taxonomies** for the ledger, the
balance sheet and the inventory (`app/seeds/*.json`; edit them on the Categories page, or the files before
the first run).

> `runserver` reloads on `.py` changes; the container (gunicorn) does not. Template and CSS
> edits are picked up without a restart (the stylesheet link is cache-busted by file mtime).

## Running on the internet

The threat model (`docs/SECURITY.md`) assumes a private network or the loopback interface; nothing
stops you putting the app on the open internet, but then the host must do four things. This
was tried against a fresh container behind Caddy with a self-signed certificate; the host-side
checklist is in `docs/deployment.md`.

1. **TLS in front.** A reverse proxy (Caddy, nginx, Traefik) terminates HTTPS and forwards to
   the container's port 8000, sending `X-Forwarded-Proto`, `X-Forwarded-Host` and
   `X-Forwarded-For` (Caddy does by default; nginx needs the `proxy_set_header` lines). The
   app never listens on the internet itself.
2. **`BASE_URL`** set to the public origin (`https://money.example`): the host Django accepts,
   the origin its CSRF check trusts, what the bookmarklets and the invitation / reset links
   bake in. Without it every page is a 400 and every form a 403.
3. **`SESSION_HTTPS_ONLY=true`**: the session cookie is `Secure` and HSTS is sent.
4. **`TRUSTED_PROXIES`**: the range the proxy connects from, so the login rate limiter sees
   real visitor addresses in `X-Forwarded-For` instead of keying everyone as the proxy. The
   reference `compose.yml` already trusts Docker's bridge range for a proxy on the host; a
   proxy container on another network or another machine is listed by its range.

Then: `manage.py check --deploy` inside the container reports no issues (two checks are
silenced on purpose: the app stamps its own security and frame headers). Keep the one gunicorn
worker (`config/gunicorn.conf.py`): the login limiter is process state. Back the data directory
up (`docs/backups.md`) — on the internet, the database is one bug away from being someone
else's.

## Packaging

`packaging/` holds every launch target — Docker image, macOS `.app`, Linux desktop entry —
so `app/` never changes for one. Docker owns port 8012 by default (the web service and
the jobs process from one image) and the desktop windows attach to it. See [`packaging/README.md`](packaging/README.md).

## Data

Everything lives in the data directory: `money.sqlite` (rows, and since ADR-0020 every upload —
photos and file Documents are rows of `blobs`) and `models/`. The schema is
numbered SQL files under `app/store/schema/` applied at start (ADR-0011, ADR-0012); the
generated diagram is [`docs/schema.mmd`](docs/schema.mmd). The app reads spreadsheet-style
field names (`"Account Type"`, `"Unit_Cost"`) through each store's field map.

Feeds: the SimpleFIN Bridge (ADR-0014, ADR-0015) is the one live source; **Settings → Feed** in the
app shows its state and, until it is set up, the exact way to claim an Access URL
(`python -m app.simplefin.claim`) and put it in `.env` as `SIMPLEFIN_ACCESS_URL`.

## License

MIT (see `LICENSE`).
