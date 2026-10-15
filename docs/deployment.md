# Deployment contract

What this repository promises to whoever runs it, and what it leaves to the host. The
Django build (ADR-0024) runs as two processes from one image: the web service `money`
and its jobs process `money-jobs`.

## This repository owns

**The image.** `packaging/docker/Dockerfile` builds from the repo root, installs the `app` and
`config` packages, collects the static files, and runs one of two processes from the same image:
the web server (the entrypoint applies the store's schema files, Django's migrations and the
first account, then gunicorn on port 8000, one worker with threads) and the jobs process
(`python manage.py run_jobs`: the feed's scheduled runs and the daily session clean-up, which
must start after the web service is healthy so only one process applies the schema). The web
service answers `GET /healthz` with `{"ok": true}`. Everything persistent lives under `DATA_DIR`, which is `/app/data` inside the
image: `money.sqlite` (rows, photos and file Documents) and `models/`. Nothing else is written to disk. The process
runs with umask 077 and keeps `DATA_DIR` at 0700 and the database at 0600, fixing a lax
mode at start and refusing to start when it cannot; the image runs as root, so a
bind-mounted data directory ends up root-owned. Threat model and the compromise runbook:
`docs/SECURITY.md`.

`FUTURE_PURCHASES_URL` (optional): where the Year plan's Pull reads future-purchases' planned
export, on demand only (ADR-0023). When both apps share a Docker network, money gets
`FUTURE_PURCHASES_URL: http://future-purchases:8000` in its `environment:` block. Unset = the
Pull is off and the buttons say so.

**The environment it reads.** Required: `SESSION_SECRET` (Django's `SECRET_KEY`; the app refuses
to start without it). Optional: `DATA_DIR` (default `./data` on the host, `/app/data` in the
image), `SESSION_MAX_AGE` (default 24 hours), `SESSION_HTTPS_ONLY` (set true behind HTTPS),
`BASE_URL` (the public origin the app is reached on, Mealie's name for it: the request `Host`
Django accepts, the origin its CSRF check trusts, and what the clipper bookmarklets and the
invitation / reset links bake in; `ALLOWED_HOSTS_EXTRA` allows more hosts, comma-separated;
`CLIP_BASE_URL` is the old name and still works with a warning),
`DEFAULT_USER` / `DEFAULT_PASSWORD` (a headless first account when no user exists, with a
password change forced at the first sign-in; unset, the first visit to `/login` is a setup form), `GITHUB_TOKEN` (optional; raises the software
clipper's GitHub limit from 60 to 5,000 requests/hour), and for the optional SimpleFIN feed
`SIMPLEFIN_ACCESS_URL` (the Bridge access URL with its `user:pass@` credential; environment
only, never the database, claimed once with `python -m app.simplefin.claim`). `.env` is this app's own file and is
read by the venv server, the desktop wrappers, and the reference compose file alike.

**A reference `compose.yml` at the repo root.** Two services from one image — `money` and
`money-jobs` — sharing `./data:/app/data` and `env_file: .env`, the web one published on
`127.0.0.1:8012:8000`, the jobs one started once the web one is healthy.
`docker compose up -d --build` is the one-command run. A larger stack defines its own services
and does not include this file.

**The desktop wrappers.** `packaging/desktop/` windows attach to whatever answers `/healthz`
on the app port and start their own server only when nothing does. Where that port is served
from is the host's business.

**The backup procedure.** `docs/backups.md`: what to copy, how to take and verify a copy. Not when.

## The host owns

- The host port (8012 in the reference compose file). The clipper bookmarklets bake in their
  origin, so `BASE_URL` is set per deployment and the bookmarklets are minted per app.
- HTTPS and the session cookie flag: something that terminates TLS in front (`tailscale serve`,
  Caddy, nginx), and `SESSION_HTTPS_ONLY=true`.
- Scheduling backups of the data directory (`docs/backups.md` says what and how, not when).
- Distributing `.env` between machines. Any script that syncs checkouts must not overwrite an
  app's `.env` with another machine's copy; that guard belongs to the script, not to this repo.
- One web server and one jobs process per data directory: the venv server and the containers
  never run against the same `DATA_DIR` at once; the two containers share it by design (the
  busy guard in `app/simplefin/sync.py` keeps a manual and a scheduled run from overlapping).

## A public deployment (the host-side checklist)

Tried on 2026-10-08 against a fresh container behind Caddy (`tls internal`); every line
below is what made it work.

1. A reverse proxy terminates TLS and forwards to the container's port 8000 with
   `X-Forwarded-Proto` (the app reads it as the scheme — `SECURE_PROXY_SSL_HEADER`),
   `X-Forwarded-Host` (honoured, `USE_X_FORWARDED_HOST`) and `X-Forwarded-For`. Caddy sends all
   three by default: `reverse_proxy money:8000`. nginx: `proxy_set_header X-Forwarded-Proto
   $scheme; proxy_set_header X-Forwarded-Host $host; proxy_set_header X-Forwarded-For
   $proxy_add_x_forwarded_for; proxy_set_header Host $host;`. Never publish 8000 itself.
2. `BASE_URL=https://money.example` (with the port if it is not 443). It feeds
   `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`; a wrong value is a 400 on every page (host
   check) or a 403 on every form (origin check).
3. `SESSION_HTTPS_ONLY=true`: `Secure` on the session cookie, HSTS on every response.
4. `TRUSTED_PROXIES`: the address or range the proxy connects from. Loopback is always
   trusted, but inside Docker a proxy on the host arrives from the bridge gateway, not
   loopback, so the reference `compose.yml` trusts `172.16.0.0/12` (only other containers can
   connect from there); a proxy container on another network, or on another machine, is
   listed by its range. Without it the login rate limiter keys every visitor as the proxy, so
   one person's five failures lock everyone out for fifteen minutes (the app logs a warning
   the first time it ignores a forwarded header for this reason). The limiter reads
   `X-Forwarded-For` from the right, past every trusted hop, so a value the client sent
   itself is never used: a proxy that appends (nginx's `$proxy_add_x_forwarded_for`,
   Traefik) and one that overwrites (Caddy) are both safe.
5. `python manage.py check --deploy` inside the container: "no issues (2 silenced)". The two
   silenced checks ask for Django's own SecurityMiddleware and XFrameOptionsMiddleware; the app
   stamps those headers itself (`app/middleware.py`). Anything else it prints is a real gap.
6. One gunicorn worker, as shipped: the login limiter and the feed's single-run lock are
   process state. Scale by threads, not workers.
7. Back up the data directory (`docs/backups.md`); keep `.env` out of the image and the repo.

What the proxy adds that a tailnet front already did: nothing new to the app. What it does
not add: authentication. The login form is on the internet; the rate limiter and the
twelve-character password rule are the guard, and `/admin/` is behind the same login.
