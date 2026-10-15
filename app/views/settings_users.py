"""Settings → Users (admins only): the members of the household with their role and last
sign-in, the open invitation links, the pending password reset links, and the actions an
admin takes — mint an invite, mint a reset link, revoke a link, deactivate or reactivate a
member, make or unmake an admin. The Django admin stays for everything else. Every action
is written to the admin log, so /admin/ shows who did what. A minted link is shown once."""

from functools import wraps

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.urls import path
from django.utils import timezone

from .. import links, web
from ..middleware import error_page
from ..models import AccessLink


def admin_only(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        if not request.user.is_superuser:
            if request.path.startswith("/api/"):
                return web.json({"detail": "Admins only"}, 403)
            return error_page(request, 403, "Admins only.")
        return view(request, *args, **kwargs)
    return inner


def _log(request, obj, message: str) -> None:
    LogEntry.objects.log_actions(request.user.pk, [obj], CHANGE, message, single_object=True)


def _context(request, **extra) -> dict:
    User = get_user_model()
    members = User.objects.order_by("-is_superuser", "username")
    open_links = [l for l in AccessLink.objects.select_related("user") if l.is_open]
    return {
        "members": members,
        "admins": sum(1 for m in members if m.is_superuser and m.is_active),
        "invites": [l for l in open_links if l.kind == AccessLink.INVITE],
        "resets": [l for l in open_links if l.kind == AccessLink.RESET],
        "new_link": None, "error": None, "invite_days": links.DEFAULT_EXPIRY_DAYS,
        **extra,
    }


def _page(request, status=200, **extra):
    return web.page(request, "settings_users.html", _context(request, **extra), status=status)


@admin_only
@web.GET
def users_page(request):
    return _page(request)


@admin_only
@web.POST
def mint_invite(request):
    note = (request.POST.get("note") or "").strip()
    try:
        days = max(1, min(90, int(request.POST.get("days") or links.DEFAULT_EXPIRY_DAYS)))
        uses = max(1, min(20, int(request.POST.get("uses") or 1)))
    except ValueError:
        return _page(request, 400, error="Days and uses must be whole numbers.")
    link, token = links.mint(AccessLink.INVITE, created_by=request.user, expires_days=days, uses=uses, note=note)
    _log(request, link, f"minted invitation {note or link.pk} ({uses} use(s), {days} day(s))")
    return _page(request, new_link={"kind": "invitation", "for": note or "anyone", "url": links.url_for(link.kind, token)})


@admin_only
@web.POST
def mint_reset(request):
    user = get_user_model().objects.filter(pk=request.POST.get("user_id") or 0).first()
    if user is None:
        return _page(request, 404, error="No such member.")
    link, token = links.mint(AccessLink.RESET, created_by=request.user, user=user)
    _log(request, link, f"minted a password reset link for {user.get_username()}")
    return _page(request, new_link={"kind": "password reset", "for": user.get_username(), "url": links.url_for(link.kind, token)})


@admin_only
@web.POST
def revoke_link(request, link_id: int):
    link = AccessLink.objects.filter(pk=link_id).first()
    if link is None:
        return _page(request, 404, error="No such link.")
    links.revoke(link)
    _log(request, link, f"revoked {link.get_kind_display().lower()} {link.note or link.pk}")
    return web.redirect("/settings/users")


def _member_or_404(request, user_id):
    return get_user_model().objects.filter(pk=user_id).first()


@admin_only
@web.POST
def set_active(request, user_id: int):
    """Body: active=1|0. The last active admin cannot be deactivated."""
    user = _member_or_404(request, user_id)
    if user is None:
        return _page(request, 404, error="No such member.")
    active = request.POST.get("active") == "1"
    with transaction.atomic():
        if not active and user.is_superuser and user.is_active and _admins_besides(user) == 0:
            return _page(request, 400, error="That is the last admin; make someone else an admin first.")
        user.is_active = active
        user.save(update_fields=["is_active"])
        if not active:
            links.end_other_sessions(user)
    _log(request, user, "reactivated the member" if active else "deactivated the member")
    return web.redirect("/settings/users")


@admin_only
@web.POST
def set_admin(request, user_id: int):
    """Body: admin=1|0. The last admin cannot be demoted."""
    user = _member_or_404(request, user_id)
    if user is None:
        return _page(request, 404, error="No such member.")
    admin = request.POST.get("admin") == "1"
    with transaction.atomic():
        if not admin and user.is_superuser and user.is_active and _admins_besides(user) == 0:
            return _page(request, 400, error="That is the last admin; make someone else an admin first.")
        user.is_superuser = admin
        user.is_staff = admin
        user.save(update_fields=["is_superuser", "is_staff"])
    _log(request, user, "made an admin" if admin else "made a member")
    return web.redirect("/settings/users")


def _admins_besides(user) -> int:
    return get_user_model().objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk).count()


urlpatterns = [
    path("settings/users", users_page),
    path("settings/users/invite", mint_invite),
    path("settings/users/reset", mint_reset),
    path("settings/users/links/<int:link_id>/revoke", revoke_link),
    path("settings/users/<int:user_id>/active", set_active),
    path("settings/users/<int:user_id>/admin", set_admin),
]
