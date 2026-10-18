"""What every Jinja page render gets beyond Django's own `request` and `csrf_token`: the
request's CSP nonce for its inline <script>/<style> blocks (app.middleware.SecurityHeadersMiddleware),
and the user's chart colours, which base.html puts on <html> as --chart-* tokens."""

from . import chart_colors as _chart_colors


def security(request) -> dict:
    return {"csp_nonce": getattr(request, "csp_nonce", "")}


def chart_colors(request) -> dict:
    colors = _chart_colors.for_user(getattr(request, "user", None))
    return {"chart_colors": colors, "chart_rows": _chart_colors.rows(colors)}
