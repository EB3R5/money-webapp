# Security

What this app protects, where the trust boundaries are, what an attacker could do at each,
which controls exist in the code today, and what to do when something goes wrong. Written
for the SQLite-first build (ADR-0010) with the optional SimpleFIN feed (ADR-0014). Every
control listed as *in place* names the module that implements it; if the code moves, this
page moves with it.

The threat model assumes one household (a few logins, one ledger), one web server and one
jobs process per data directory, reached over a private network (a tailnet), the loopback
interface, or the open internet behind a TLS-terminating reverse proxy set up as
`docs/deployment.md` describes (`BASE_URL`, the HTTPS-only cookie, `TRUSTED_PROXIES`). It is
not designed for multi-tenant use: every login sees the whole ledger.

## 1. Assets and classification

| Asset | Where it lives | Class | Why |
|---|---|---|---|
| **Access URL** (SimpleFIN) | `SIMPLEFIN_ACCESS_URL` in the environment (`.env` or a secrets manager). Never the database. | **Critical** | Read-only access to every linked bank: balances and full transaction history, for as long as it is valid. Revocable only from the Bridge. |
| **Setup token** (SimpleFIN) | Nowhere after use; passes through stdin of the claim CLI once. | **Critical until claimed, then worthless** | Whoever claims it first owns the Access URL. Single-use: a 403 on claim means someone else already did. |
| **Database** (`DATA_DIR/money.sqlite` + WAL/SHM) | The Data directory. | **High** | Every transaction, balance, budget, inventory row, the audit log, and the accounts (`auth_user`: PBKDF2 password hashes; `django_session`: the live sessions). |
| **Session secret** (`SESSION_SECRET`) | Environment. | **High** | Django's `SECRET_KEY`: signs the session cookie and the CSRF token. Whoever has it can forge a cookie for an existing session id. |
| **Uploads and model** (`blobs` rows in the database; `DATA_DIR/models/`) | The Data directory. | **Medium** | Photos and file Documents are personal and live inside the database since ADR-0020; the model file is a pickle the app loads and runs (see §3, data directory integrity). |
| **Session cookie** | The browser. | **High while valid** | A bearer for the whole app until it expires (24 h default) or the secret rotates. |
| **Logs** | Container stdout / the host's journal. | **Low by construction** | Access lines (client address, method, path and query string, status) and app messages. No request bodies, no credentials: URL userinfo, `Authorization` values and the token segment of an invitation or reset link's path are masked before any handler sees them (`app/logging_setup.py`; the gunicorn access log is a Python logger, so its request lines pass through the same filter), provider errors carry an HTTP status and never a body, and the Bridge client logs at WARNING only. A Ledger search term can appear in a query string. A reverse proxy's own log is the host's to redact: it sees the link path in clear. |
| **Backups** | Wherever the host keeps them (`docs/backups.md`). | Same as the database. | A copy of the Data directory is the database: password hashes, sessions, every row. |

## 2. Trust boundaries

```
                         ┌──────────────────────────────────────────────────────┐
                         │  Host (the machine that runs the stack)              │
   ┌───────────┐  HTTPS  │  ┌────────────────┐     ┌──────────────────────────┐ │
   │  Browser  │ ──────▶ │  │ TLS front      │ ──▶ │ Container / venv server  │ │
   │ (laptop,  │ private │  │ (tailnet, or a │ http│  gunicorn + Django       │ │
   │  phone)   │ ◀────── │  │  reverse proxy)│ ◀── │  ── session cookie ──    │ │
   └───────────┘  cookie │  └────────────────┘     │  ── CSRF token ──        │ │
        ▲                │        127.0.0.1:8012   │  ── CSP / headers ──     │ │
        │ bookmarklet    │                         └────┬───────────┬─────────┘ │
        │ (opens the app │                              │           │           │
        │  origin only)  │     ┌────────────────────────▼──┐   ┌────▼────────┐  │
        │                │     │ Data directory (DATA_DIR) │   │ Environment │  │
        └────────────────┤     │  0700 dir, 0600 database, │   │ .env /      │  │
                         │     │  (uploads inside), models/│   │ secrets mgr │  │
                         │     └───────────────────────────┘   └─────────────┘  │
                         └──────────┬─────────────────────────┬─────────────────┘
                                    │ HTTPS + Basic auth
                                    ▼
                         ┌──────────────────────┐
                         │ SimpleFIN Bridge     │
                         │ (banks behind it)    │
                         └──────────────────────┘
```

Boundaries, from the outside in:

- **B1 Browser ↔ server.** Crossed by every request. Guarded by the login (username +
  password), the session cookie, the CSRF token, and the response headers.
- **B2 Network.** The server listens on loopback; a host-owned front (`docs/deployment.md`)
  terminates TLS — a tailnet admits its peers only, a reverse proxy on the internet admits
  everyone to the login form. Anything else on the LAN never reaches the port.
- **B3 Server ↔ Data directory.** The process is the only reader and writer; the OS mode bits
  keep other users on the host out.
- **B4 Server ↔ environment.** Secrets enter as environment variables at start; nothing in the
  app writes them anywhere (not the database, not a log, not an error page).
- **B5 Server ↔ SimpleFIN Bridge.** Outbound only, HTTPS, Basic auth from the split Access URL.
  The Bridge's data is untrusted input.
- **B6 Server ↔ arbitrary web** (inventory clipper only). A logged-in user can ask the server to
  download a product image from a URL they supply.

## 3. Threat model

STRIDE-style, one row per threat that matters here. *In place* points at the code; *residual*
is what remains and what §4 defers.

| # | Threat | Boundary | STRIDE | In place | Residual |
|---|---|---|---|---|---|
| T1 | **LAN neighbour** connects to the app port | B2 | S, I | The deployment contract publishes the port on loopback only (`127.0.0.1:8012`, `docs/deployment.md`); the TLS front is the only thing in front of it. Every request still needs a session or a per-user API token (`app/middleware.py` `AuthGateMiddleware`, `ApiTokenMiddleware`; no static secret). | A misconfigured publish to `0.0.0.0` exposes the login form, not the data. Rate limiting still applies. |
| T2 | **Network peer** (another device on the private network, or anyone on the internet behind a proxy) opens the app | B1/B2 | S | Login: username + password against `django.contrib.auth` (PBKDF2), 5 failures per 15 min per address+username and 20 per address (`app/security.py` `LoginRateLimiter`; the address is the connection's, or behind a trusted proxy the rightmost `X-Forwarded-For` hop no trusted proxy wrote — a value the client sent itself is never believed, so the lockout cannot be dodged by forging the header; an untrusted proxy in front makes every visitor one address, which the app logs a warning about), an unknown username costs a dummy hash and gets the same "Invalid credentials." (`app/views/auth.py`); the admin's own login form is never shown (`/admin/login/` redirects to `/login`). No self-signup; a second person joins through an invitation link (T16) or is added in `/admin/`. With no account at all, `/login` is a one-time setup form (rate-limited, CSRF-checked, closed for good once a user exists); a headless deployment seeds an admin from `DEFAULT_USER` / `DEFAULT_PASSWORD` who must change the password at first sign-in (`app/accounts.py`, `app/views/auth.py`). | On a tailnet its ACLs (host-owned) decide who can even reach the port; on the internet the rate limiter and the password rule are the guard. The second factor (TOTP) was dropped with ADR-0024. |
| T3 | **Stolen laptop or session cookie** | B1 | S, E | Sessions are rows (`django_session`): the cookie `money_session` carries only the id, `HttpOnly`, `SameSite=Lax`, `Secure` behind HTTPS, a 24 h idle timeout, renewed on every request (thirty days when the login form's Remember me is ticked; there is no absolute cap, so a session in daily use lives until it is revoked); login cycles the session key; logout deletes the row. Revoke one session by deleting its row (or all of a user's) in `/admin/` or the shell; rotating `SESSION_SECRET` invalidates every cookie at once. | A session row outlives its cookie until the jobs process' daily clean-up removes it. |
| T4 | **Cross-site request** from a page the user visits | B1 | T | CSRF: Django's `CsrfViewMiddleware` with the secret in the session (no csrftoken cookie on the shared host), the token in `X-CSRF-Token` or the `csrfmiddlewaretoken` field, and Django's `Origin`/`Referer` checks behind HTTPS (`CSRF_TRUSTED_ORIGINS` from `BASE_URL`), plus `Sec-Fetch-Site` same-origin/none (`app/middleware.py` `FetchMetadataMiddleware`); `frame-ancestors 'none'` and `X-Frame-Options: DENY` stop clickjacking (the document raw route alone answers with `'self'`/`SAMEORIGIN`, and sandboxes an uploaded HTML page so it gets an opaque origin, ADR-0016); `form-action 'self'`. | None known. |
| T5 | **Script injection** through stored text (a bank description, a rule) | B1/B5/B6 | T, E | Jinja autoescapes templates; AG Grid renders cell values as text and the grid's own renderers build DOM nodes (`app/static/js/grid-factory.js`); CSP allows only `'self'` and nonced scripts, so an injected `<script>` cannot run (`app/middleware.py` `SecurityHeadersMiddleware`). Provider error text is stripped of control characters, redacted, and truncated before it is stored (`app/simplefin/sync.py` `sanitize_msg`). | `style-src 'unsafe-inline'` remains for AG Grid (see the middleware docstring). The page scripts' `innerHTML` uses have not been audited row by row; CSP is the backstop for any that interpolate stored text. |
| T6 | **Leaked git history** (a pushed `.env`, a fork) | B4 | I | `.env`, `data/`, and `*.sqlite` are gitignored; no secret is ever written by the app, so none can land in a commit through it. | Anything that was ever committed is burned: rotate it (§6). |
| T7 | **Bridge breach** or a revoked/reissued Access URL | B5 | I, D | The Access URL is read-only at the bank; the client raises on 403/402 with status only, the run is marked `failed`, earlier chunks stay committed, the cursor does not advance (`app/simplefin/sync.py`). | A breached Bridge can read what the banks expose. The response is to revoke there (§5). |
| T8 | **Malicious provider data** (a Bridge feeding crafted rows) | B5 | T, D | Pydantic models with `extra="ignore"` and finite `Decimal` amounts (`app/simplefin/models.py`); feed rows never overwrite app-owned fields (`TXN_PROTECT`, `ACCOUNT_PROTECT`); a deterministic row id per (account, provider txn id); T5 covers rendering. | A provider can still flood transactions or shift balances; the deletions audit log and per-run history (`sync_runs`) make it visible and reversible, not impossible. |
| T9 | **Log leakage** (a pasted log line, a log shipped elsewhere) | B4 | I | `RedactingFilter` runs from the log record factory, so every record — whichever logger, whichever handler — is redacted at creation (URL userinfo, the configured Access URL credential, `Authorization` values, invitation and reset link paths, the traceback text); httpx at WARNING so no request URL is logged; the error boundary logs exceptions through the same filter and renders a generic page (`error.html`), never a traceback; `DEBUG = False`, no schema or docs routes. | The access log carries query strings (a Ledger search term). |
| T10 | **Request-budget exhaustion** (the Bridge's 24 requests/day) | B5 | D | A per-day budget (`SIMPLEFIN_DAILY_BUDGET`, default 20) counted across `sync_runs`; a run with no budget left is `skipped_budget`; one run at a time (`SyncBusy`, 409); a startup catch-up only when the last success is stale (`app/simplefin/schedule.py`). | Manual "Sync now" clicks spend the same budget; the Activity page shows what is left. |
| T11 | **Resource exhaustion** of the server | B1 | D | Body limit 64 KiB (25 MiB for multipart uploads on API routes and the document text paths; the login, setup, register and reset forms, which anyone can reach, stay at 64 KiB whatever the content type claims) by `Content-Length`; a chunked body (a transfer encoding and no length) is refused with 411 up front, since WSGI cannot count it as it streams; Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` is the backstop (`app/middleware.py` `BodyLimitMiddleware`); the image fetch caps at 10 MB and 10 s. | No request-rate limit outside login; fine behind a tailnet. |
| T12 | **Another user on the host** reads the database | B3 | I | At start the process sets umask 077 and `database.init()` makes the Data directory 0700 and the database (plus WAL/SHM/journal) 0600; a lax mode is fixed and logged, an unfixable one refuses to start (`app/store/permissions.py`). Uploads are rows keyed by a uuid (no path at all, ADR-0020); the model path is built from its name and digest only (`app/store/files.py`). Django's own tables (users, sessions) live in the same 0600 file and never show on the Data page (`app/store/database.py` `HIDDEN_TABLE_PREFIXES`). | Root reads anything. Inside the image the process **is** root (§4 deferred). |
| T13 | **Data directory integrity**: whoever can write it can run code | B3 | E | The model file is joblib (pickle) loaded in-process (`app/ml_model.py`), and the schema files are applied verbatim. The 0700 directory is the control. | Treat write access to `DATA_DIR` as code execution. Restores go into a fresh directory you trust. |
| T14 | **Server-side request** through the clipper's image fetch | B6 | I | Requires a session and the CSRF token; only `http(s)` URLs; `image/*` responses only; 10 MB and 10 s caps; failures return a message, not the body (`app/image_fetch.py`). | The URL is not checked against private address ranges: a logged-in user could probe loopback or LAN services and learn whether they answer with an image. Deferred (§4). |
| T16 | **A leaked invitation or reset link** | B1 | S | Invitations are the only way to sign up (no open registration): an admin mints a link with an expiry (a week by default) and a use count (one), hands it over by hand; the database holds only a hash of the token; the register page is rate-limited and CSRF-checked, counts the use atomically, and answers a closed or unknown link with a plain 404 (`app/links.py`, `app/views/auth.py`). A password reset link is the same object for one user (a day, one use) and signs that user's other sessions out when spent. A link can be revoked on Settings → Users or in `/admin/`; every mint and revoke, every deactivation and promotion is written to the admin log. | Whoever holds an open link before its holder uses it can join as a member (not an admin), or take over the one account a reset link is for: hand links over on a channel you trust, and revoke one that went astray. |
| T15 | **Forged health probes / status reads** | B1 | I | `/healthz` returns `{"ok": true}` and nothing else; `/api/health`, `/sync/simplefin/status` and the Feed settings page (`/settings/feed`, which shows that a credential is set and never what it is) sit behind the auth gate. | None known. |
| T17 | **A leaked API token** | B1 | S | A token is per user, named, hashed in the database, shown once, revocable on `/account`; a bearer request acts as that user with no session and is exempt from CSRF (it has no browser); an unknown or revoked bearer is a 401 at once and never falls through to a cookie; a flagged (default-password) user's token is refused like their session; a bearer is accepted on `/api/` and `/sync/` routes only, so a token cannot open a page, reach `/account` (where tokens are minted), Settings → Users or the Django admin, and a leaked token cannot mint another token, an invitation or a reset link (`app/tokens.py`, `app/middleware.py` `ApiTokenMiddleware`). Bearer values are masked in logs. | A leaked token is the user on the API until revoked: keep tokens in a secrets store, name them for the script that holds them, revoke what you no longer recognise. |

## 4. Controls

**In place** (each verified in the module named):

- API tokens: per user, hashed, shown once, revocable; bearer requests are CSRF-exempt and
  sessionless; no static secret anywhere (`app/tokens.py`, `app/middleware.py`).
- Login: `django.contrib.auth` (PBKDF2; a bcrypt hash verifies and is upgraded), rate limit,
  timing-equal unknown-user path, generic error, session cycled, 24 h lifetime, no token
  bypass, forced password change for the bootstrap default (`app/views/auth.py`,
  `app/accounts.py`, `app/security.py`).
- Session cookie `money_session`: a row id only, `HttpOnly`, `SameSite=Lax`, `Secure` when
  `SESSION_HTTPS_ONLY`; a day, or thirty days with Remember me, revocable either way
  (`config/settings.py`, `app/views/auth.py`). The app refuses to start with an empty
  `SESSION_SECRET` (`config/settings.py`).
- CSRF token on every unsafe request (Django, secret in the session); `Sec-Fetch-Site` check
  (`app/middleware.py`).
- Response headers on every response: CSP with nonced scripts, `nosniff`, `Referrer-Policy:
  same-origin` (not `no-referrer`: that makes browsers send `Origin: null` on POSTs, which
  Django's CSRF check behind HTTPS rejects), `Permissions-Policy`, `X-Frame-Options: DENY`, `Cache-Control: no-store` off
  `/static`, HSTS behind HTTPS (`app/security.py` `response_headers`, stamped by
  `app/middleware.py`).
- Error boundary: unhandled exceptions are logged redacted and answered with `error.html`;
  a failed request's store writes are rolled back; `DEBUG` is off (`app/middleware.py`,
  `config/settings.py`).
- Body limits: 64 KiB, 25 MiB multipart, 411 for a chunked body (`app/middleware.py`).
- Data directory: umask 077, 0700/0600, refuse-or-fix at start (`app/store/permissions.py`).
- Uploads in the database, keyed by uuid, kind-separated on the routes (`app/store/blobs.py`); path
  safety for the model file (`app/store/files.py`).
- Credential-in-env-not-DB for the feed; split URL so the credential never enters a request
  URL or an exception (`app/simplefin/client.py`, ADR-0014).
- Claim CLI: prints only the Access URL to stdout, everything else to stderr; `--out` writes
  a 0600 file and never overwrites; 403 is reported as "already claimed" (`app/simplefin/claim.py`).
- Log redaction everywhere, provider text sanitized before storage (`app/logging_setup.py`,
  `app/simplefin/sync.py`).
- Daily request budget, one run at a time, per-run history, cursor advances per committed chunk
  (`app/simplefin/sync.py`, `app/simplefin/schedule.py`).
- Feed rows never overwrite app-owned fields; provider input validated by Pydantic
  (`app/simplefin/sync.py`, `app/simplefin/models.py`).
- Hard deletes are audited to `deletions` first (ADR-0005, `app/audit.py`).
- Nothing loads from a third-party origin: AG Grid, echarts, html-to-image are vendored
  (`app/static/vendor/`).

**Deferred** (decided not to build yet; revisit when the threat changes):

- Database file encryption (SQLCipher or a filesystem layer). The host's encrypted volume is the guard.
- A second factor (TOTP was dropped with ADR-0024; WebAuthn / passkeys if one returns).
- Encrypted backups and a backup schedule inside the app (`docs/backups.md` leaves both to the host).
- Alerting on `partial` or `failed` Sync runs. Today: the Activity page and `GET /api/health`
  for something else to poll.
- A non-root user in the container image (the process runs as root; a bind-mounted data
  directory ends up root-owned 0700).
- Private-address blocking on the clipper's image fetch (T14).
- An app-level log of login attempts (today: the gunicorn access log's 401/429 lines on `POST /login`).
- A request-rate limit outside the login form.

## 5. Secret lifecycle

**Setup token → Access URL (SimpleFIN).** Create the setup token in the Bridge on the trusted
box, then claim it there, via stdin, in the same minute:

```bash
python -m app.simplefin.claim --stdin < setup-token.txt   # or paste and Ctrl-D
```

Only the Access URL reaches stdout: pipe it into your secrets manager or paste it into `.env`
as `SIMPLEFIN_ACCESS_URL`, then delete the token file. Never put the setup token or the Access
URL in a chat, a ticket, a commit, or a screenshot. `--out PATH` writes a 0600 file if you
need one; it refuses to overwrite.

- **403 on claim** means the token was already used. Treat it as compromised: revoke the app in
  the Bridge, create a new setup token, claim again.
- **403 during a sync** means the Access URL was revoked or reissued. The run is `failed` and
  the cursor stays. Unset `SIMPLEFIN_ACCESS_URL`, revoke the app in the Bridge if you did not
  revoke it yourself, re-claim with a new setup token, set the new URL, restart.
- **402 during a sync** means the Bridge subscription lapsed. No data is at risk; runs fail until
  it is renewed. Renew, then "Sync now" on the Activity page.

**Rotation.** Revoke the app in the Bridge (this kills the old Access URL), create a new setup
token, claim, replace the variable, restart. Do it on any suspicion, when a machine that held
`.env` leaves the household, and after any leak of logs from before the redaction filter.

**Session secret.** Generate with `python -c "import secrets;print(secrets.token_hex(32))"`.
Rotating it logs every browser out at once; that is the intended emergency response to a
stolen cookie or laptop. There is no partial rotation.

**Login credential.** Change your own password at `/account`. For someone who cannot sign in,
mint a **password reset link** — `/admin/` under Access links (kind: Password reset) or
`manage.py reset_link <user>` — and hand it over on a channel you trust: one use, a day's
expiry, shown once, hashed in the database; the page sets the new password, signs every other
session of that account out and forgives its login lockout (`/reset/<token>`,
`app/views/auth.py`). The app sends no email, so the login page says "ask your admin".
`manage.py changepassword <user>` on the box still works. With no user at all, `/login` is the
setup form; a headless deployment sets `DEFAULT_USER` / `DEFAULT_PASSWORD` and the next start
creates that admin (`manage.py bootstrap_admin`).

**Where secrets never go.** The database (`auth_user` holds only password hashes), logs
(redacted), error pages (generic), tickets and pull requests (describe, never
paste).

## 6. Runbook

Related procedures: `docs/deployment.md` (what the host owns: port, TLS, `.env`
distribution, one server per data directory) and `docs/backups.md` (taking and verifying a
copy of the data directory).

**Compromise checklist.** Work top to bottom; each line is independent, so skip nothing.

1. Rotate `SESSION_SECRET` and restart: every session is now invalid.
2. Reset each password (a reset link, or `manage.py changepassword <user>`) and delete every `django_session` row.
3. Revoke the app in the SimpleFIN Bridge, claim a new Access URL (§5), replace, restart.
4. Check the Data directory modes; the app fixes lax ones at start, but look for files you
   did not create under `models/` (a foreign model file is code); a `photos/` or
   `documents/` directory should not exist any more (ADR-0020).
5. Review the Activity page: runs you did not trigger, `failed`/`partial` runs, an unexpected
   window. Review `deletions` for rows you did not delete.
6. Review the access log for addresses you do not recognise (greps below).
7. If git history is involved (a `.env` or a database pushed by mistake), treat anything
   ever committed as burned: rotate it, then rewrite or recreate the repository.
8. Restore from a verified backup into a fresh directory only if the database itself is suspect.

**Log-review greps.** Logs are wherever the host keeps container output; with the reference
compose file (the jobs container has the scheduled runs, the web one the requests):

```bash
LOGS="docker compose logs --no-log-prefix --since 24h money money-jobs"

$LOGS | grep -E 'POST /login HTTP/1\.[01]" (401|429)'         # failed / throttled logins
$LOGS | grep -E '" (403|413) '                                # CSRF / cross-site / oversized
$LOGS | grep -E 'unhandled error on'                          # the error boundary fired
$LOGS | grep -E 'SimpleFIN (sync failed|chunk .* failed|scheduled sync: (failed|partial))'
$LOGS | grep -E 'data directory permissions tightened'        # something loosened the modes
$LOGS | grep -E 'SimpleFIN startup catch-up|scheduled sync:'  # runs and their outcomes
$LOGS | grep -oE '^[0-9a-f.:]+' | sort | uniq -c | sort -rn   # who talked to the server
```

A credential in any of those lines is a bug in the redaction filter: report it, then rotate.
