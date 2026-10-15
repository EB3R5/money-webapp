"""/account: change your own password (Django's PasswordChangeForm and validators: twelve
characters at least, not a common password, not your username) and manage your API tokens
(mint one, shown once; revoke one). The one page a user whose password is still the default
may open; saving a new password clears the flag and keeps the session. Minting a token
while flagged is refused."""

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.urls import path

from .. import tokens, web
from ..accounts import must_change_password, set_must_change
from ..models import ApiToken


def _render(request, form, *, status=200, new_token=None, token_error=None):
    errors = [str(e) for field in form.errors.values() for e in field]
    live = ApiToken.objects.filter(user=request.user, revoked_at__isnull=True)
    return web.page(request, "account.html",
                    {"errors": errors, "forced": must_change_password(request.user) or bool(request.GET.get("forced")),
                     "tokens": live, "new_token": new_token, "token_error": token_error},
                    status=status)


def account_view(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)       # the session survives the hash change
            set_must_change(user, False)
            return web.redirect("/")
        return _render(request, form, status=400)
    if request.method != "GET":
        return web.json({"detail": "Method Not Allowed"}, 405)
    return _render(request, PasswordChangeForm(request.user))


@web.POST
def mint_token(request):
    """Body: name. The token is shown once, on the page that follows."""
    if must_change_password(request.user):
        return _render(request, PasswordChangeForm(request.user), status=403,
                       token_error="Change the default password first.")
    name = (request.POST.get("name") or "").strip()
    if not name:
        return _render(request, PasswordChangeForm(request.user), status=400, token_error="Give the token a name.")
    token, raw = tokens.mint(request.user, name)
    return _render(request, PasswordChangeForm(request.user), new_token={"name": token.name, "value": raw})


@web.POST
def revoke_token(request, token_id: int):
    token = ApiToken.objects.filter(pk=token_id, user=request.user).first()
    if token is None:
        return web.json({"ok": False, "error": "not found"}, 404)
    tokens.revoke(token)
    return web.redirect("/account")


urlpatterns = [
    path("account", account_view),
    path("account/tokens", mint_token),
    path("account/tokens/<int:token_id>/revoke", revoke_token),
]
