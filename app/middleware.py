"""The request pipeline on Django (ADR-0024); the policies it stamps (the CSP, the
headers, the login rate limiter) live in app/security.py, the tests in tests/test_security.py.

Outermost first (config/settings.py MIDDLEWARE):
  SecurityHeadersMiddleware   CSP nonce + the headers on every response; the error boundary
  BodyLimitMiddleware         413 over the limit, 411 for a non-GET without Content-Length
  FetchMetadataMiddleware     Sec-Fetch-Site must be same-origin for unsafe methods (with Django's CSRF)
  ApiTokenMiddleware          `Authorization: Bearer` is a per-user token, CSRF-exempt, no session
  AuthGateMiddleware          a session (or a token) for everything but the exempt prefixes
  StoreScopeMiddleware        one store connection per request, rolled back on a failed request
  DomainErrorMiddleware       a DomainError raised by an operation is its JSON 4xx
`csrf_failure` is Django's CSRF_FAILURE_VIEW; `error_page` renders error.html."""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.template.loader import render_to_string

from . import security
from .accounts import must_change_password
from .config import BODY_LIMIT_BYTES, TEXT_BODY_PATHS, UPLOAD_LIMIT_BYTES
from .store import database
from .web import DomainError

_log = logging.getLogger("money.security")

# Paths reachable without a session: the login pages, static files, the health probe, and
# the admin (which runs its own login and staff check).
EXEMPT_PREFIXES = ("/login", "/setup", "/register", "/reset", "/logout", "/static", "/healthz", "/admin")
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# What a signed-in user whose password is still the bootstrap default may still reach:
# the change-password page, signing out, and what every page needs. Not the admin.
FLAGGED_PREFIXES = ("/account", "/login", "/setup", "/logout", "/static", "/healthz")


def is_exempt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in EXEMPT_PREFIXES)


def _open_while_flagged(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in FLAGGED_PREFIXES)


def _is_api(request: HttpRequest) -> bool:
    return request.path.startswith("/api/")


def error_page(request: HttpRequest, status: int, message: str) -> HttpResponse:
    html = render_to_string("error.html", {"status": status, "message": message}, request=request)
    return HttpResponse(html, status=status)


def _see_other(url: str) -> HttpResponse:
    response = HttpResponse(status=303)
    response["Location"] = url
    return response


def _rejected(request: HttpRequest) -> HttpResponse:
    if _is_api(request):
        return JsonResponse({"ok": False, "error": "request rejected"}, status=403)
    return error_page(request, 403, "Request rejected.")


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """Django's CSRF_FAILURE_VIEW: JSON under /api/, the error page elsewhere."""
    return _rejected(request)


# --- security headers + error boundary ----------------------------------------------------

class SecurityHeadersMiddleware:
    """Mints the request's CSP nonce (`request.csp_nonce`), stamps the headers on every
    response — a page, JSON, static, a 404, a 500 — and is the error boundary: a view
    exception is logged through the redacting filter and rendered as the HTML error page
    with the same headers. A response that already carries a CSP or X-Frame-Options keeps
    its own (security.ROUTE_OWNED_HEADERS: the document raw route, the clip popups)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        for key, value in security.response_headers(request.csp_nonce, request.path):
            if key in security.ROUTE_OWNED_HEADERS and response.has_header(key):
                continue
            response[key] = value
        return response

    def process_exception(self, request: HttpRequest, exc: Exception):
        _log.exception("unhandled error on %s %s", request.method, request.path)
        return error_page(request, 500, "Something went wrong. It has been logged.")


# --- request body limit --------------------------------------------------------------------

class BodyLimitMiddleware:
    """413 for a declared body over the limit, before anything reads it. Multipart gets the
    upload limit (photos, the Item bundle's PNG), as do the JSON paths that carry a
    document's text. WSGI has no streaming body, so a chunked request (Transfer-Encoding
    without a Content-Length) is refused with 411 rather than counted as it streams; a
    request with neither header has no body."""

    def __init__(self, get_response, *, limit: int = BODY_LIMIT_BYTES,
                 upload_limit: int = UPLOAD_LIMIT_BYTES, upload_paths: tuple = TEXT_BODY_PATHS):
        self.get_response = get_response
        self.limit, self.upload_limit, self.upload_paths = limit, upload_limit, tuple(upload_paths)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return self.get_response(request)
        large = (request.META.get("CONTENT_TYPE", "").startswith("multipart/form-data")
                 or request.path.startswith(self.upload_paths))
        limit = self.upload_limit if large else self.limit
        declared = request.META.get("CONTENT_LENGTH", "")
        if declared in ("", None):
            if request.META.get("HTTP_TRANSFER_ENCODING"):
                return JsonResponse({"ok": False, "error": "length required"}, status=411)
            return self.get_response(request)
        try:
            length = int(declared)
        except ValueError:
            length = 0
        if length > limit:
            return JsonResponse({"ok": False, "error": "request body too large"}, status=413)
        return self.get_response(request)


# --- fetch metadata (beside Django's CSRF token check) -------------------------------------

class FetchMetadataMiddleware:
    """For an unsafe method the browser's Sec-Fetch-Site, when sent, must be same-origin or
    none; a cross-site or same-site(-subdomain) request is refused before the view. Django's
    CsrfViewMiddleware checks the token; this adds the fetch-metadata rule the FastAPI
    middleware had. Honours the test client's `_dont_enforce_csrf_checks` the same way."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if (request.method in UNSAFE_METHODS and not security.csrf_exempt(request.path)
                and not getattr(request, "_dont_enforce_csrf_checks", False)
                and not request.META.get("HTTP_AUTHORIZATION", "").startswith("Bearer ")):   # a token, not a browser

            site = request.META.get("HTTP_SEC_FETCH_SITE")
            if site and site not in ("same-origin", "none"):
                return _rejected(request)
        return self.get_response(request)


# --- API tokens -----------------------------------------------------------------------------

class ApiTokenMiddleware:
    """After AuthenticationMiddleware: a request with `Authorization: Bearer <token>` is the
    token's user — exempt from the CSRF check (a script has no form token) and never given
    a session. A bearer that is unknown, revoked, or whose user is inactive is a 401 at once;
    it never falls through to the cookie. Logged by the token's name, never its value."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if auth.startswith("Bearer "):
            from .tokens import find_live, touch
            token = find_live(auth[7:].strip())
            if token is None:
                return JsonResponse({"detail": "Not authenticated"}, status=401)
            request.user = token.user
            request.api_token = token
            request.auth_actor = "token"
            request._dont_enforce_csrf_checks = True
            touch(token)
        return self.get_response(request)


# --- auth gate ----------------------------------------------------------------------------

class AuthGateMiddleware:
    """Every request needs a signed-in user, except the exempt prefixes: a session, or a
    per-user API token (ApiTokenMiddleware) — never a static secret. Browser misses redirect
    to /login; /api/* get 401. A user whose
    password is still the bootstrap default may open /account (and sign out) only: pages
    redirect there, /api/* get 403, the admin too. Tests flip settings.MONEY_AUTH_GATE to skip the gate (the old
    app.state.auth_disabled)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not getattr(settings, "MONEY_AUTH_GATE", True):
            return self.get_response(request)
        if not request.user.is_authenticated:
            if is_exempt(request.path):
                return self.get_response(request)
            if _is_api(request):
                return JsonResponse({"detail": "Not authenticated"}, status=401)
            return _see_other(settings.LOGIN_URL)
        if not _open_while_flagged(request.path) and must_change_password(request.user):
            if _is_api(request):
                return JsonResponse({"detail": "Password change required"}, status=403)
            return _see_other("/account?forced=1")
        return self.get_response(request)


# --- store scope --------------------------------------------------------------------------

class StoreScopeMiddleware:
    """One store connection for everything the request does, committed when the view
    returns (ADR-0011). Django turns a view exception into a response before it reaches
    this middleware's call, so the exception is noted in process_exception and the scope
    rolled back instead of committed — as the FastAPI gate did by letting it propagate."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with database.scope() as conn:
            response = self.get_response(request)
            if getattr(request, "_store_failed", False) or response.status_code >= 500:
                conn.rollback()
        return response

    def process_exception(self, request: HttpRequest, exc: Exception):
        if not isinstance(exc, DomainError):
            request._store_failed = True
        return None


class DomainErrorMiddleware:
    """A DomainError raised anywhere in an operation (a bad field, a duplicate item, an
    in-use delete) is the JSON 4xx the browser gets — the one place that mapping lives."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exc: Exception):
        if isinstance(exc, DomainError):
            return JsonResponse({"ok": False, "error": exc.message, **exc.extra}, status=exc.status)
        return None
