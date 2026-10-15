# Packaging targets

Everything that launches the app lives here; `app/` never changes for a new target.
`packaging/` has no `__init__.py` and is never imported — it would shadow the PyPI
`packaging` library. Scripts run the launcher by path.

**Operating model.** Docker owns the app's port (8012). The `.app` window and the
Linux desktop entry attach to whatever answers `/healthz` there; only when nothing does, they
start Django's dev server on a free port (after the schema, the migrations and the first account) and stop it when the window closes. The venv server
(`python manage.py runserver 8012`) is for development: run it with the container stopped, or on
another port. The scheduled job (the SimpleFIN feed, when its Access URL is set) runs inside whichever process is the server, so never
have two servers on the same database at once.

## server (venv)

```bash
python -m venv .venv && ./.venv/bin/pip install -e ".[desktop,dev]"
./.venv/bin/python manage.py runserver 8012
```

## docker

Container-specific config, set in the compose file rather than `.env`: `DATA_DIR` is
`/app/data` (bind-mounted), and the clipper bookmarklets bake in the app's origin
(`BASE_URL`), so they are minted per host port.

Build context is the repo root; the image collects the static files at build, its entrypoint applies the schema, the migrations and the first account, then runs gunicorn on 8000 (or `python manage.py run_jobs` for the jobs container) and health-checks `/healthz`.
Config comes from the environment — `.env` is dockerignored. The repo's `compose.yml` builds this Dockerfile for both `money` and `money-jobs`, reads `.env`, and publishes `127.0.0.1:8012:8000`; a larger stack defines the same two services itself.

```bash
docker build -f packaging/docker/Dockerfile -t money-webapp .
docker run --rm -p 127.0.0.1:8099:8000 --env-file .env money-webapp   # see note
```

Note: `docker run --env-file` is literal — it keeps the double quotes `.env` uses around values,
so `SESSION_MAX_AGE="604800"` fails `int()`. Compose's `env_file` parses quotes like python-dotenv
does, so the compose path just works; for a bare `docker run`, strip the quotes first.

## desktop/launcher.py

Shared pywebview launcher; the CONFIG block at the top is the only per-repo difference.
`./.venv/bin/python packaging/desktop/launcher.py` needs the `desktop` extra.

## desktop/macos

`build.sh` compiles `launcher.c`, renders the icon with `make_icon.py` (needs pyobjc, which
pywebview brings in), assembles and ad-hoc signs `/Applications/money.app`. The launcher is a
compiled Mach-O, not a shell script: TCC attributes Documents-folder access to the code
signature, and a zsh launcher is attributed to `/bin/zsh` and dies with EPERM reading the venv.
Approve the Documents prompt on first launch; every rebuild re-signs, so macOS asks again.
`build.sh` compiles its own checkout's path into the launcher (`-DMONEY_REPO`); the `MONEY_REPO`
environment variable overrides it at launch, and `MONEY_BUNDLE_ID` names the bundle.

## desktop/linux

Debian/Ubuntu, pywebview's GTK/WebKit2 backend. `install.sh` checks the apt packages
(`python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1`), drops `system-gi.pth` into the venv so the
system `gi` module is visible, renders `money.desktop` with this repo's path, and installs it with
`money.png` under `~/.local/share`. `run.sh` is what the entry executes. `uninstall.sh` reverses it.
