---
title: Django replaces FastAPI; self-contained accounts - Plan
type: feat
date: 2026-10-08
topic: django-port
artifact_contract: ce-unified-plan/v1
artifact_readiness: in-progress
product_contract_source: dialogue
execution: code
---

# Django replaces FastAPI; self-contained accounts - Plan

## Goal Capsule

- **Objective:** money-webapp-next's whole HTTP layer runs on **Django 5.2 LTS** (gunicorn,
  the existing Jinja templates through Django's Jinja2 backend, sync function views at the
  same paths with the same JSON shapes) over the existing hand-written SQLite store layer
  made synchronous. Accounts are **self-contained, Mealie-style**: `django.contrib.auth` in
  the app's own database, an admin seeded from `DEFAULT_USER` / `DEFAULT_PASSWORD` on first
  start (default `changeme`, forced change at first login), no self-signup, more users through
  `/admin/`, password only, the existing user's password kept. No shared accounts service.
- **Product authority:** #199 (#199) and
  ADR-0024; decisions chosen in dialogue on 2026-10-08.
- **Stop conditions:** the `django` branch is never deployed before FastAPI is removed (#208);
  the cutover (#209) is human-driven.

## Context

On 2026-10-07 the user decided the household's apps with a login move to Django; the host
map planned a shared Postgres accounts service and the library app first. On 2026-10-08 the
user changed course for money-next: go there now, Django instead of FastAPI, accounts in the
app itself the way Mealie keeps its users, password only. The shared-login map stays parked.

Today: 29 FastAPI routers (~132 routes), 40 store modules on hand-written SQL with numbered
schema files, 42 Jinja templates and JS islands (no HTMX), a hardened middleware stack
(CSRF, CSP nonce, body limit, rate limiter; `docs/SECURITY.md`), 819 tests.

## Key Decisions

- **D1 — Django is the HTTP layer; the store layer stays.** Views one-to-one with the
  routers; `Store` / `Field` + numbered SQL untouched; the ORM only for what Django itself
  needs. Kept because 757 store-shaped tests and 17 schema files have no ORM equivalent worth
  re-expressing.
- **D2 — The store layer is synchronous first.** `aiosqlite` → `sqlite3`, `scope()` /
  `acquire()` keep their names on the same context variable; a request middleware opens the
  scope; jobs open their own. Done in #200 with an AST codemod.
- **D3 — Django's tables live in `money.sqlite`.** One file is still the whole backup
  (ADR-0020's spirit). A view never writes both the store and Django's tables in one request;
  `busy_timeout` on both connections; Django's transactions are `IMMEDIATE`. The Data page and
  the census hide `sqlite_` / `django_` / `auth_` / `money_` tables.
- **D4 — Accounts are self-contained.** `bootstrap_admin` seeds the default user or imports the
  legacy credential row (bcrypt hash as `bcrypt$…`, upgraded to PBKDF2 on the next login);
  `/login` is username + password with the existing rate limiter; sessions are rows; `/admin/`
  manages users. TOTP is dropped.
- **D5 — Security parity is the gate.** `tests/test_security.py` is ported before any page
  beyond the Ledger: our own headers middleware (CSP nonce, no-store, HSTS behind HTTPS,
  route-owned opt-out), the body limit (413; a chunked body is 411 on WSGI), Django's CSRF with
  the secret in the session and the existing `X-CSRF-Token` header, the Sec-Fetch-Site rule as
  a middleware, the auth gate with the same exempt prefixes and miss shapes, a store scope
  that rolls back a failed request, one app-level mapping of `DomainError` to its JSON 4xx.
- **D6 — Shared-host cookies.** Session cookie `money_session` (the other FastAPI apps on the
  tailnet host keep Starlette's `session`); `CSRF_USE_SESSIONS`, so no csrftoken cookie;
  `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` from `CLIP_BASE_URL`; the forwarded-proto header
  for `tailscale serve`. `SECRET_KEY` is the existing `SESSION_SECRET` (no .env churn).
- **D7 — One env surface.** `config/settings.py` reads `app/config.py`; nothing is configured
  twice. Logging stays with the redacting filter, now installed at the log record factory so
  every record is redacted at creation.
- **D8 — The scheduler leaves the web process.** `manage.py run_jobs` (blocking APScheduler) in
  a `money-next-jobs` compose service sharing the image, env and data volume; a cross-process
  busy guard on the sync runs table.
- **D9 — Test harness.** pytest-django; the per-test database is a copy of one template
  (store schema + Django migrations) built once per session; `tests/client.py` speaks the
  httpx call shape so a ported test only loses its `await`s; `settings.MONEY_AUTH_GATE`
  replaces `app.state.auth_disabled`; the FastAPI client stays as `legacy_client` until the
  last router moves.
- **D10 — Branch and pace.** Long-lived `django` branch, one PR per slice into it, never
  stacked; merged to `main` by the cutover slice. CI runs on PRs into `django` too.

## Slices

| # | Issue | Slice |
|---|---|---|
| 1 | #200 | Store layer goes sync (merged, PR #210) |
| 2 | #201 | Django skeleton, security parity gate, the Ledger on Django |
| 3 | #202 | Mealie-style accounts: bootstrap admin, password-only login, forced change, /admin |
| 4 | #203 | Categorization and categories |
| 5 | #204 | Card collections: accounts, inventory, software, kits, documents |
| 6 | #205 | Dashboard, reports, insights, planning, budgets, metrics |
| 7 | #206 | Tax, credit, health, investments, balances, Data page, Activity |
| 8 | #207 | SimpleFIN pages, clipper handouts, the `run_jobs` sidecar |
| 9 | #208 | Remove FastAPI, switch the container and compose, update the docs |
| 10 | #209 | Cutover on the box, drop the legacy credential table, merge `django` into `main` |

Slices 4–8 are independent of each other once slice 3 lands.

## Per-view port rules

Each router module becomes `app/views/<same name>.py` exposing `urlpatterns`; `app/urls.py`
lists the modules in the old mount order (first match wins, as before). `{x}` → `<str:x>`;
the Budgets prefix becomes full paths. `CardCollection.urlpatterns()` and
`Grid.urlpatterns(seg)` replace the router factories. Per call: `request.json()` →
`web.read_json(request)`; `guard(x)` / `JSONResponse(x)` → `web.json(x)`;
`TemplateResponse` → `web.page(request, name, ctx, headers=...)`; `RedirectResponse` →
`web.redirect(url)` (303); `request.query_params` → `request.GET`; `request.state.csp_nonce`
→ `request.csp_nonce`; `UploadFile` → `request.FILES`; `@web.GET` / `@web.POST` for the
method. A bare `return {…}` must become `web.json(…)`. Tests: `async def test_` → `def test_`,
drop `await`, `legacy_client` → `store_client`.

## Verification

Every slice: `pytest` green. Slice 2: `manage.py check --deploy` clean but for the silenced
header checks; curl against gunicorn shows the CSP nonce, nosniff, no-store and
X-Frame-Options on `/healthz`, a 401 JSON miss under `/api/`, a 303 to `/login` elsewhere, a
403 page on a form POST without a token, a cached static file with the CSP headers, a 413 on a
70,000-byte JSON body. Slice 3: browser login with `changeme` → forced change → Ledger; a
second user from `/admin/`; a sixth wrong password → 429. Slice 9: `docker build`, the
container's `/healthz`, the jobs container's catch-up on Activity. Slice 10: the cutover
runbook, the tailnet form and fetch POSTs, both containers healthy.
