"""Accounts are self-contained, Mealie-style (ADR-0024): `django.contrib.auth` users in
this app's own database, no self-signup, more users through /admin/.

ensure_admin() is what the first start runs (`manage.py bootstrap_admin`, idempotent):
  - users exist                          → nothing
  - DEFAULT_USER and DEFAULT_PASSWORD set → that superuser, flagged to change the password
                                            at first login, and a loud warning in the log
                                            (headless deployments)
  - nothing                              → nothing: the first visit to /login is the setup
                                            form (app/views/auth.py), where the first
                                            person chooses their own username and password.
(The FastAPI build's single credential row was imported once, at the cutover; its bcrypt
hash still verifies through PASSWORD_HASHERS and is upgraded on the next login.)"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Profile

log = logging.getLogger("money.accounts")



def must_change_password(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return Profile.objects.filter(user_id=user.pk, must_change_password=True).exists()


def set_must_change(user, flag: bool) -> None:
    Profile.objects.update_or_create(user=user, defaults={"must_change_password": flag})


def needs_setup() -> bool:
    """No account yet: /login is the setup form."""
    return not get_user_model().objects.exists()


def create_first_admin(username: str, password: str, *, must_change: bool):
    """The first account, a superuser. Refuses when one exists (two browsers on the setup
    form at once: the second one loses, inside the same transaction)."""
    User = get_user_model()
    with transaction.atomic():          # IMMEDIATE on SQLite: the write lock is taken up front
        if User.objects.exists():
            raise AlreadySetUp()
        user = User.objects.create_superuser(username=username, password=password)
        set_must_change(user, must_change)
    return user


class AlreadySetUp(Exception):
    """An account exists; the setup form is closed."""


def ensure_admin() -> str:
    """Make sure someone can sign in. Returns what happened, for the command's output."""
    User = get_user_model()
    if User.objects.exists():
        return "users exist; nothing to do"
    username = getattr(settings, "DEFAULT_USER", "") or ""
    password = getattr(settings, "DEFAULT_PASSWORD", "") or ""
    if not (username and password):
        return "no user yet; the first visit to /login is the setup form (or set DEFAULT_USER and DEFAULT_PASSWORD)"
    user = create_first_admin(username, password, must_change=True)
    log.warning("no user existed: created %r with the default password from DEFAULT_USER / "
                "DEFAULT_PASSWORD. Sign in and change it now; the app insists until you do.", username)
    return f"created the default admin {username!r} (password change required at first login)"
