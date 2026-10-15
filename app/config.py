"""App configuration — loaded from the project's .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent          # <repo>/app
PROJECT_DIR = BASE_DIR.parent                        # <repo>

load_dotenv(PROJECT_DIR / ".env")

# Data directory (ADR-0010): the SQLite file plus photos/ and models/. Relative paths
# resolve against the project dir so `./data` means money-webapp-next/data.
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
if not DATA_DIR.is_absolute():
    DATA_DIR = PROJECT_DIR / DATA_DIR

# Sessions (config/settings.py). SESSION_SECRET is Django's SECRET_KEY — must be set in prod
# (generate: python -c "import secrets;print(secrets.token_hex(32))"). SESSION_MAX_AGE
# is the login lifetime in seconds; default 24 hours (86400). Bump for longer (7d = 604800).
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", "86400"))
# Mark the session cookie Secure (HTTPS-only). Keep false for local http dev; set true
# in prod (behind HTTPS), else the browser drops the cookie over plain http.
SESSION_HTTPS_ONLY = os.environ.get("SESSION_HTTPS_ONLY", "false").lower() == "true"

# Auto-categorization ML model — runs in-process; the joblib file lives under the Data
# directory's models/ (app/store/files.py) with a `model_versions` row tracking the
# current version. No external call at request time; the first model is trained from the
# categorized ledger (POST /api/ml/retrain) and refreshed the same way.
ML_MODEL_NAME = os.environ.get("ML_MODEL_NAME", "category_model")
ML_CONF_MIN = float(os.environ.get("ML_CONF_MIN", "0.0"))   # hide ML suggestions below this

# The public origin the app is reached on (Mealie's BASE_URL): the request hosts Django
# accepts, the origins its CSRF check trusts, and what the clipper bookmarklets and the
# invitation / reset links bake in. Unset: loopback only, and links carry a path alone.
# CLIP_BASE_URL is the old name for the same thing; it still works, with a warning at start.
BASE_URL = os.environ.get("BASE_URL", "").strip().rstrip("/")
# The reverse proxies whose X-Forwarded-For the login rate limiter believes, as addresses or
# CIDR ranges, comma-separated. Loopback is always trusted (`tailscale serve`, a proxy on the
# same host); a proxy in another container or on another machine must be listed here, else
# every visitor counts as the proxy's address and shares one lockout bucket.
TRUSTED_PROXIES = [p.strip() for p in os.environ.get("TRUSTED_PROXIES", "").split(",") if p.strip()]
CLIP_BASE_URL = os.environ.get("CLIP_BASE_URL", "").strip().rstrip("/")
BASE_URL_FROM_LEGACY = bool(not BASE_URL and CLIP_BASE_URL)
if BASE_URL_FROM_LEGACY:
    BASE_URL = CLIP_BASE_URL

# future-purchases, read on demand by the Year plan's Pull (ADR-0023). Unset = the Pull is
# off and the button says so. On a shared Docker network: http://future-purchases:8000.
FUTURE_PURCHASES_URL = os.environ.get("FUTURE_PURCHASES_URL", "").strip().rstrip("/")

# Software clipper (app/software_clip.py). Optional GitHub token: raises the REST limit
# from 60/hour per IP to 5,000/hour for repo lookups (`gh auth token` or a fine-grained
# PAT with no scopes). Unset = anonymous requests.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

# SimpleFIN feed (app/simplefin). The Access URL is the read-only credential for every
# linked bank: environment only, never the database. Claim it once with
# `python -m app.simplefin.claim --stdin`. Unset = the feed is off.
SIMPLEFIN_ACCESS_URL = os.environ.get("SIMPLEFIN_ACCESS_URL", "").strip()
# Bridge limits: ≤ 24 requests/day (we keep a margin), windows ≤ 90 days per call and the
# Bridge warns above 45; banks refresh daily. Overlap re-reads the tail so late-posting
# rows are caught; the initial lookback is the first run's window.
SIMPLEFIN_DAILY_BUDGET = int(os.environ.get("SIMPLEFIN_DAILY_BUDGET", "20"))
SIMPLEFIN_INITIAL_LOOKBACK_DAYS = int(os.environ.get("SIMPLEFIN_INITIAL_LOOKBACK_DAYS", "90"))
SIMPLEFIN_OVERLAP_DAYS = int(os.environ.get("SIMPLEFIN_OVERLAP_DAYS", "5"))
SIMPLEFIN_MAX_WINDOW_DAYS = int(os.environ.get("SIMPLEFIN_MAX_WINDOW_DAYS", "45"))
# Scheduling (app/simplefin/schedule.py): a run every SYNC_INTERVAL_HOURS at a fixed minute
# (banks refresh daily; a random fixed minute spreads load), plus a catch-up shortly after
# start when the last success is older than SYNC_STALE_HOURS.
SYNC_INTERVAL_HOURS = int(os.environ.get("SYNC_INTERVAL_HOURS", "6"))
SYNC_CRON_MINUTE = int(os.environ.get("SYNC_CRON_MINUTE", "17"))
SYNC_STALE_HOURS = int(os.environ.get("SYNC_STALE_HOURS", "12"))

# Request body limits (app/security.py): JSON and form posts are small; multipart carries
# photo uploads and the Item bundle's PNG.
BODY_LIMIT_BYTES = int(os.environ.get("BODY_LIMIT_BYTES", str(64 * 1024)))
UPLOAD_LIMIT_BYTES = int(os.environ.get("UPLOAD_LIMIT_BYTES", str(25 * 1024 * 1024)))
# JSON bodies that carry a document's text (a note save, the preview) use the upload limit;
# the domain cap is documents.TEXT_CAP.
TEXT_BODY_PATHS = ("/api/documents/",)

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def static_version(rel: str = "css/app.css") -> int:
    """mtime of a static file, for cache-busting the <link>/<script> URL. Recomputed
    per render so an edited file refetches even without a server restart."""
    try:
        return int((STATIC_DIR / rel).stat().st_mtime)
    except OSError:
        return 0
