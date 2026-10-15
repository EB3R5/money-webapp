"""Signing in and out, the first account, joining by invitation, and a password reset by link (ADR-0024, Mealie-style accounts). Username + password against
django.contrib.auth; the login rate limiter from the FastAPI era stays (5 failures per
15 min per address+username, 20 per address, checked before any password work); a wrong
username and a wrong password get the same generic answer and cost the same (the model
backend hashes a dummy password for an unknown user). A successful login cycles the session
and the CSRF token and sends a user who still has the default password to /account. Remember me keeps the
session for thirty days instead of a day; logout and a revoked row end it either way."""

import ipaddress

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.urls import path
from django.utils.http import url_has_allowed_host_and_scheme

from .. import links, web
from ..accounts import AlreadySetUp, create_first_admin, must_change_password, needs_setup, set_must_change
from ..middleware import error_page
from ..models import AccessLink
from ..security import limiter

_BAD = "Invalid credentials."
_SLOW = "Too many attempts. Try again in a few minutes."


def _trusted_proxy(addr: str) -> bool:
    """Loopback always; otherwise what TRUSTED_PROXIES lists (addresses or CIDR ranges)."""
    if addr in ("127.0.0.1", "::1", ""):
        return True
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    for entry in getattr(settings, "TRUSTED_PROXIES", []):
        try:
            if ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request) -> str:
    """The peer's address the rate limiter keys on: the first X-Forwarded-For hop when the
    connection comes from a trusted proxy (`tailscale serve` on loopback, or one listed in
    TRUSTED_PROXIES), else the connection's own address."""
    addr = request.META.get("REMOTE_ADDR", "")
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded and _trusted_proxy(addr):
        return forwarded.split(",")[0].strip()
    return addr


def _safe_next(request) -> str:
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return nxt
    return "/"


def _form(request, error, status=200, headers=None):
    return web.page(request, "login.html", {"error": error, "next": request.GET.get("next", "")},
                    status=status, headers=headers)


def login_view(request):
    if request.method == "GET":
        if request.user.is_authenticated:
            return web.redirect("/")
        if needs_setup():
            return web.redirect("/setup")
        return _form(request, None)
    if request.method != "POST":
        return web.json({"detail": "Method Not Allowed"}, 405)
    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""
    ip = client_ip(request)
    wait = limiter.retry_after(ip, username)
    if wait:
        return _form(request, _SLOW, 429, {"Retry-After": str(wait)})
    user = authenticate(request, username=username, password=password)
    if user is None:
        limiter.record_failure(ip, username)
        return _form(request, _BAD, 401)
    limiter.record_success(ip, username)
    login(request, user)                           # cycles the session key, rotates the CSRF token
    if request.POST.get("remember"):               # thirty days instead of the day the cookie gets
        request.session.set_expiry(settings.REMEMBER_ME_AGE)
    if must_change_password(user):
        return web.redirect("/account?forced=1")
    return web.redirect(_safe_next(request))


# --- the first account, and the ones invited after it --------------------------------------

SETUP_BUCKET = "__setup__"       # the limiter's username key for the setup form
REGISTER_BUCKET = "__register__"
RESET_BUCKET = "__reset__"


def _account_errors(username: str, p1: str, p2: str) -> list[str]:
    """What is wrong with a new account's username and password, in the user's words."""
    errors = []
    if not username:
        errors.append("A username is required.")
    elif get_user_model().objects.filter(username__iexact=username).exists():
        errors.append("That username is taken.")
    if p1 != p2:
        errors.append("The two passwords do not match.")
    else:
        try:
            validate_password(p1, user=get_user_model()(username=username))   # unsaved: the similarity check
        except ValidationError as e:
            errors.extend(str(m) for m in e.messages)
    return errors


def _setup_form(request, errors, username="", status=200):
    return web.page(request, "setup.html", {"errors": errors, "username": username}, status=status)


def setup_view(request):
    """The one-time setup form: with no account in the database, the first person chooses
    the admin's username and password here (the default path; DEFAULT_USER /
    DEFAULT_PASSWORD is the headless alternative). Closed for good once a user exists."""
    if not needs_setup():
        return web.redirect("/login")
    if request.method == "GET":
        return _setup_form(request, [])
    if request.method != "POST":
        return web.json({"detail": "Method Not Allowed"}, 405)
    ip = client_ip(request)
    wait = limiter.retry_after(ip, SETUP_BUCKET)
    if wait:
        return web.page(request, "setup.html", {"errors": [_SLOW], "username": ""}, status=429,
                        headers={"Retry-After": str(wait)})
    username = (request.POST.get("username") or "").strip()
    p1, p2 = request.POST.get("password1") or "", request.POST.get("password2") or ""
    errors = _account_errors(username, p1, p2)
    if errors:
        limiter.record_failure(ip, SETUP_BUCKET)
        return _setup_form(request, errors, username, 400)
    try:
        user = create_first_admin(username, p1, must_change=False)
    except AlreadySetUp:
        return web.redirect("/login")
    limiter.record_success(ip, SETUP_BUCKET)
    login(request, user)
    return web.redirect("/")


def register_view(request, token: str):
    """/register/<token>: the page an invitation link opens. The link must be open (not
    expired, revoked or used up) or the answer is a plain 404 — never a form. The new
    account is a regular member of the household, signed in at once; the link's use is
    counted atomically, so a one-use link cannot admit two."""
    try:
        link = links.find_open(AccessLink.INVITE, token)
    except links.LinkNotOpen:
        return error_page(request, 404, "This invitation is no longer valid. Ask for a new one.")
    ctx = {"errors": [], "username": "", "action": links.path_for(AccessLink.INVITE, token)}
    if request.method == "GET":
        return web.page(request, "register.html", ctx)
    if request.method != "POST":
        return web.json({"detail": "Method Not Allowed"}, 405)
    ip = client_ip(request)
    wait = limiter.retry_after(ip, REGISTER_BUCKET)
    if wait:
        return web.page(request, "register.html", {**ctx, "errors": [_SLOW]}, status=429,
                        headers={"Retry-After": str(wait)})
    username = (request.POST.get("username") or "").strip()
    p1, p2 = request.POST.get("password1") or "", request.POST.get("password2") or ""
    errors = _account_errors(username, p1, p2)
    if errors:
        limiter.record_failure(ip, REGISTER_BUCKET)
        return web.page(request, "register.html", {**ctx, "errors": errors, "username": username}, status=400)
    try:
        links.spend(link)
    except links.LinkNotOpen:
        return error_page(request, 404, "This invitation is no longer valid. Ask for a new one.")
    user = get_user_model().objects.create_user(username, password=p1)
    limiter.record_success(ip, REGISTER_BUCKET)
    login(request, user)
    return web.redirect("/")


def reset_view(request, token: str):
    """/reset/<token>: the page an admin-minted password reset link opens (the app sends no
    email). Open link only, else a plain 404. A valid submission sets the user's password,
    spends the link, signs every other session of that user out, clears a forced-change
    flag, and signs them in here."""
    try:
        link = links.find_open(AccessLink.RESET, token)
    except links.LinkNotOpen:
        return error_page(request, 404, "This reset link is no longer valid. Ask your admin for a new one.")
    user = link.user
    if user is None or not user.is_active:
        return error_page(request, 404, "This reset link is no longer valid. Ask your admin for a new one.")
    ctx = {"errors": [], "username": user.get_username(), "action": links.path_for(AccessLink.RESET, token)}
    if request.method == "GET":
        return web.page(request, "reset.html", ctx)
    if request.method != "POST":
        return web.json({"detail": "Method Not Allowed"}, 405)
    ip = client_ip(request)
    wait = limiter.retry_after(ip, RESET_BUCKET)
    if wait:
        return web.page(request, "reset.html", {**ctx, "errors": [_SLOW]}, status=429, headers={"Retry-After": str(wait)})
    p1, p2 = request.POST.get("password1") or "", request.POST.get("password2") or ""
    errors = []
    if p1 != p2:
        errors.append("The two passwords do not match.")
    else:
        try:
            validate_password(p1, user=user)
        except ValidationError as e:
            errors.extend(str(m) for m in e.messages)
    if errors:
        limiter.record_failure(ip, RESET_BUCKET)
        return web.page(request, "reset.html", {**ctx, "errors": errors}, status=400)
    try:
        links.spend(link)
    except links.LinkNotOpen:
        return error_page(request, 404, "This reset link is no longer valid. Ask your admin for a new one.")
    user.set_password(p1)
    user.save(update_fields=["password"])
    set_must_change(user, False)
    links.end_other_sessions(user)
    limiter.record_success(ip, RESET_BUCKET)
    limiter.record_success(ip, user.get_username())      # a reset forgives the lockout that caused it
    login(request, user)
    return web.redirect("/")


@web.POST
def logout_view(request):
    logout(request)
    return web.redirect("/login")


urlpatterns = [
    path("login", login_view),
    path("setup", setup_view),
    path("register/<str:token>", register_view),
    path("reset/<str:token>", reset_view),
    path("logout", logout_view),
]
