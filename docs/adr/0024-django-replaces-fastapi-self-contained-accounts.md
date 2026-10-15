# Django replaces FastAPI; accounts are self-contained

Status: **accepted** (2026-10-08, with the last page slice; the production cutover ran the same day and is
#209 (#209)). Parent: Django replaces
FastAPI; self-contained Mealie-style accounts (#199). Amends ADR-0003
(the page model stays: server-rendered Jinja, JS islands, no SPA) and supersedes the
`aiosqlite` wording of ADR-0011 (the store modules, the hand-written SQL and the numbered
schema files stay; the driver is the standard `sqlite3` module and every store call is
synchronous). Accepted when the last slice merges `django` into `main`.

**The HTTP layer is Django 5.2 LTS.** The 29 FastAPI routers become Django function views at
the same paths with the same JSON shapes, rendered through Django's Jinja2 backend over the
existing templates; the app runs under gunicorn, one worker with threads. Nothing about the
data moves: `money.sqlite`, the stores, the blobs, the ML model file and the numbered schema
files are untouched, and the Django ORM is used only for what Django itself needs (users,
sessions, admin, migrations, a one-row profile), kept in the same database file so one file
is still the whole backup. A view never writes both the store and Django's tables in one request; the store's
own connection commits when the request's scope closes, Django's when its session saves.

**Accounts live in this app, Mealie-style.** `django.contrib.auth` holds the users. The first
start with no user seeds an admin from `DEFAULT_USER` / `DEFAULT_PASSWORD` (default
`changeme`, which forces a password change at first login) or imports the one legacy
credential row with its bcrypt hash, so the existing password keeps working. There is no
self-signup; more users are added in `/admin/`. Login is username + password, rate-limited
as before; the TOTP second factor is dropped. Sessions are rows, so revoking one is deleting
it. No shared accounts service and no second database: a login shared across several
apps stays a later decision.

**The store layer is synchronous.** `database.scope()` and `acquire()` keep their names and
their context-variable semantics as plain context managers; a request middleware opens the
scope, scheduler jobs open their own. The feed's single-run lock is a thread lock. The
scheduler leaves the web process for a `run_jobs` management command in a sidecar container
sharing the data volume. Tables whose names start with `sqlite_`, `django_`, `auth_` or
`money_` are hidden from the table listing, the Data page and the census.

_Why Django over keeping FastAPI with a login bolted on:_ the login, user management, admin,
sessions, CSRF and password hashing are the parts of a web framework worth not writing twice;
Django ships every one of them, tested, with a security track record, and the one-user
hardening this app carries (rate limiter, CSP nonce, body limit, no-store, fetch-metadata
check) ports as middleware. One framework in the container beats two.

_Consequences:_ the security checklist in `docs/SECURITY.md` is re-verified line by line on
Django before any page beyond the Ledger moves (the parity gate); WSGI has no streaming body,
so a non-GET without `Content-Length` is a 411 rather than a counted 413; the `django` branch
is never deployed before FastAPI is removed, because during the port the async handlers call
the now-blocking stores.
