"""What every Jinja page render gets beyond Django's own `request` and `csrf_token`: the
request's CSP nonce for its inline <script>/<style> blocks (app.middleware.SecurityHeadersMiddleware)."""


def security(request) -> dict:
    return {"csp_nonce": getattr(request, "csp_nonce", "")}
