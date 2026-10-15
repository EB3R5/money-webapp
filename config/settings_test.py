"""Settings for pytest: pytest-django calls django.setup() before tests/conftest.py is
imported, and the settings refuse an empty secret, so one is supplied here."""

import os

os.environ.setdefault("SESSION_SECRET", "pytest-only-not-a-real-secret")

from .settings import *  # noqa: E402,F401,F403

WHITENOISE_AUTOREFRESH = True       # serve app/static straight from disk; no collected staticfiles/ in tests
