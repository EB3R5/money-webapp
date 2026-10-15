"""The Jinja environment Django renders the app's templates with: its globals and
filters (`css_v` for cache-busting static URLs; the Planning
formatters in app/jinja_filters.py). `csrf_token` and `request` are injected by Django's
backend per render; `csp_nonce` by app.context_processors."""

from jinja2 import Environment

from app.config import static_version
from app.jinja_filters import FILTERS


def environment(**options) -> Environment:
    env = Environment(**options)
    env.globals["css_v"] = static_version
    env.filters.update(FILTERS)
    return env
