"""Django settings (ADR-0024). One env surface: every value Django needs is read from
`app/config.py`, which loads the project's .env, so the container, the desktop launcher and
the tests configure one thing. Django's own tables (users, sessions, admin, migrations) live
in the same `money.sqlite` as the stores; a view never writes both in one request."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from app import config as c
from app.logging_setup import configure_logging

# A public build refuses to serve with an unsigned session (ADR-0010's first run): an empty
# secret would let anyone forge the login cookie.
if not c.SESSION_SECRET:
    raise ImproperlyConfigured(
        "SESSION_SECRET is empty. Set it in .env (generate one with "
        "`python -c \"import secrets;print(secrets.token_hex(32))\"`) and start again.")
SECRET_KEY = c.SESSION_SECRET
DEBUG = False

# Hosts and origins: loopback for the container probe and the desktop launcher, the compose
# service name, and the public origin (BASE_URL: the tailnet host behind `tailscale serve`,
# which forwards the scheme, or whatever reverse proxy fronts a public deployment).
_base = urlsplit(c.BASE_URL) if c.BASE_URL else None
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "money",
                 *([_base.hostname] if _base and _base.hostname else []),
                 *[h.strip() for h in os.environ.get("ALLOWED_HOSTS_EXTRA", "").split(",") if h.strip()]]
CSRF_TRUSTED_ORIGINS = [f"{_base.scheme}://{_base.netloc}"] if _base and _base.netloc else []
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app.apps.MoneyConfig",
]

# Outermost first. The order is load-bearing: headers wrap everything (static files and
# error pages included); the body limit runs before any body is read; CSRF and the
# fetch-metadata check sit between the session and the auth gate; the store scope is the
# innermost so a request's writes commit after the view and before the session saves.
MIDDLEWARE = [
    "app.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "app.middleware.BodyLimitMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "app.middleware.FetchMetadataMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "app.middleware.ApiTokenMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "app.middleware.AuthGateMiddleware",
    "app.middleware.StoreScopeMiddleware",
    "app.middleware.DomainErrorMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
APPEND_SLASH = False          # the routes are exact

TEMPLATES = [
    {
        # The app's pages: the existing Jinja templates, unchanged. `csrf_token` and
        # `request` come from the backend; `csp_nonce` from the context processor.
        "BACKEND": "django.template.backends.jinja2.Jinja2",
        "DIRS": [c.TEMPLATES_DIR],
        "APP_DIRS": False,
        "OPTIONS": {
            "environment": "config.jinja2.environment",
            "context_processors": ["app.context_processors.security"],
        },
    },
    {
        # Django's own templates: the admin only.
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "app.context_processors.security",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": c.DATA_DIR / "money.sqlite",       # the stores' file (ADR-0020: one file, one backup)
        "OPTIONS": {
            "timeout": 5,                           # == app/store/database.py BUSY_TIMEOUT_MS
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;",
            "transaction_mode": "IMMEDIATE",        # take the write lock up front, no deferred upgrade stall
        },
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sessions are rows (revocable). The cookie has the app's own name so other apps on the
# same host keep theirs. The CSRF secret rides in the session, so no csrftoken cookie
# exists to collide either.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "money_session"
SESSION_COOKIE_AGE = c.SESSION_MAX_AGE
REMEMBER_ME_AGE = 30 * 24 * 3600                    # the login form's Remember me: thirty days
SESSION_COOKIE_SECURE = c.SESSION_HTTPS_ONLY
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_SAVE_EVERY_REQUEST = True                   # sliding expiry, as the signed cookie had

CSRF_USE_SESSIONS = True
CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"              # app/static/js/csrf.js sends X-CSRF-Token
CSRF_FAILURE_VIEW = "app.middleware.csrf_failure"
CSRF_COOKIE_SECURE = c.SESSION_HTTPS_ONLY

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",   # verifies bcrypt$… hashes, upgraded to PBKDF2 on login
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
]
LOGIN_URL = "/login"
MONEY_AUTH_GATE = True                              # tests flip it (the old app.state.auth_disabled)
# The first account for a headless deployment: set both and the first start creates it
# (flagged for a password change). Unset, the first visit to /login is a setup form instead.
BASE_URL = c.BASE_URL                               # the origin links and bookmarklets are minted for
TRUSTED_PROXIES = c.TRUSTED_PROXIES                 # whose X-Forwarded-For the rate limiter believes
DEFAULT_USER = os.environ.get("DEFAULT_USER", "").strip()
DEFAULT_PASSWORD = os.environ.get("DEFAULT_PASSWORD", "")

STATIC_URL = "/static/"
STATICFILES_DIRS = [c.STATIC_DIR]
STATIC_ROOT = c.PROJECT_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compressed, not Manifest: the templates bust caches with `?v=css_v` themselves.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True                       # dev and tests serve app/static without collectstatic

DATA_UPLOAD_MAX_MEMORY_SIZE = c.UPLOAD_LIMIT_BYTES  # backstop under app.middleware.BodyLimitMiddleware
FILE_UPLOAD_PERMISSIONS = 0o600

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# Django's SecurityMiddleware and XFrameOptionsMiddleware are not used: app.middleware
# .SecurityHeadersMiddleware stamps every header itself (CSP nonce, HSTS behind HTTPS, the
# route-owned opt-out), so the two checks that ask for them are silenced on purpose.
SILENCED_SYSTEM_CHECKS = ["security.W001", "security.W002"]

# The redacting filter owns logging (app/logging_setup.py); Django's default config is not
# installed, so nothing mails admins and every record passes the filter.
LOGGING_CONFIG = None
configure_logging()
# gunicorn and `manage.py` configure no root handler: without one the app's INFO lines
# (sync runs, the jobs' schedule) would never reach the container's stdout.
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
if c.BASE_URL_FROM_LEGACY:
    logging.getLogger("money").warning(
        "CLIP_BASE_URL is the old name of BASE_URL: rename it in .env (it still works for now)")
