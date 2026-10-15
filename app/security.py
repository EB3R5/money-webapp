"""Login rate limiting, the response headers and the CSP.

Rate limiting — in-process, per (client IP, username) and per IP.

A sliding window of failed attempts: 5 per 15 minutes for one username from one address,
20 per 15 minutes for the address regardless of username, checked before any password
work so a lockout costs nothing. A success clears the username's bucket. In-process
state is enough for one server per data directory; it resets on restart, which is fine
for a single-user app behind a tailnet."""

from __future__ import annotations

import time
from collections import defaultdict, deque

WINDOW_S = 15 * 60
PER_USER = 5
PER_IP = 20


class LoginRateLimiter:
    def __init__(self, *, per_user: int = PER_USER, per_ip: int = PER_IP, window_s: int = WINDOW_S):
        self.per_user, self.per_ip, self.window_s = per_user, per_ip, window_s
        self._user: dict[tuple[str, str], deque] = defaultdict(deque)
        self._ip: dict[str, deque] = defaultdict(deque)

    @staticmethod
    def _key(ip: str, username: str) -> tuple[str, str]:
        return (ip or "", (username or "").strip().lower())

    def _prune(self, dq: deque, now: float) -> None:
        cutoff = now - self.window_s
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def retry_after(self, ip: str, username: str, now: float | None = None) -> int:
        """Seconds until another attempt is allowed; 0 when it is allowed now."""
        now = time.time() if now is None else now
        waits = []
        for dq, limit in ((self._user[self._key(ip, username)], self.per_user), (self._ip[ip or ""], self.per_ip)):
            self._prune(dq, now)
            if len(dq) >= limit:
                waits.append(int(dq[0] + self.window_s - now) + 1)
        return max(waits) if waits else 0

    def record_failure(self, ip: str, username: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._user[self._key(ip, username)].append(now)
        self._ip[ip or ""].append(now)

    def record_success(self, ip: str, username: str) -> None:
        self._user.pop(self._key(ip, username), None)


limiter = LoginRateLimiter()


# =====================================================================================
# The response headers and the CSP (stamped by app.middleware.SecurityHeadersMiddleware),
# and the CSRF exemptions the fetch-metadata middleware honours.
# =====================================================================================

from .config import SESSION_HTTPS_ONLY

CSRF_EXEMPT_PREFIXES = ("/healthz", "/static")


def csrf_exempt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in CSRF_EXEMPT_PREFIXES)


def content_security_policy(nonce: str) -> str:
    """Scripts: self plus the request nonce, nothing inline without it. Styles: self plus
    'unsafe-inline' — AG Grid positions rows and cells with inline style attributes (no
    nonce can cover attributes), so a strict style-src blanks every grid. No nonce in
    style-src on purpose: a nonce there would make browsers ignore 'unsafe-inline'. Our own
    markup carries no style attributes; its <style> blocks are nonced anyway for the day
    the grid no longer needs the allowance."""
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
        "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )


def popup_csp(nonce: str) -> str:
    """The clip popup's CSP: the global policy with https: images, so the candidate
    thumbnails a bookmarklet harvested off a store page can preview before the server
    downloads the ticked ones. Nothing else widens."""
    return content_security_policy(nonce).replace("img-src 'self' data: blob:;",
                                                  "img-src 'self' data: blob: https:;")


# A view may set these two itself (the document raw route frames an uploaded HTML page in a
# sandbox and a PDF in the browser's viewer, the clip popups allow https images); the
# middleware then leaves them alone. Every other header is always stamped.
ROUTE_OWNED_HEADERS = ("Content-Security-Policy", "X-Frame-Options")


def response_headers(nonce: str, path: str) -> list[tuple[str, str]]:
    """Every header a response carries, in order: the CSP first. No-store off /static;
    HSTS only when the cookie is HTTPS-only (i.e. behind TLS) — read per request, so a
    settings change needs no restart."""
    out = [
        ("Content-Security-Policy", content_security_policy(nonce)),
        ("X-Content-Type-Options", "nosniff"),
        # same-origin, not no-referrer: under no-referrer a browser sends `Origin: null` on
        # every form and fetch POST, and Django's CSRF check behind HTTPS rejects a null
        # origin (it needs the Origin, or the Referer, to match the site). same-origin keeps
        # both for our own pages and sends nothing to any other site.
        ("Referrer-Policy", "same-origin"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
        ("X-Frame-Options", "DENY"),
    ]
    if not (path == "/static" or path.startswith("/static/")):
        out.append(("Cache-Control", "no-store"))
    if SESSION_HTTPS_ONLY:
        out.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
    return out
