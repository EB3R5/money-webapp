"""Minting and spending access links (app/models.py AccessLink): the token is random, the
database keeps its hash, the link is shown once. `mint()` returns (link, token); `spend()`
counts a use atomically and refuses a link that is not open; `url_for()` builds the link
from BASE_URL, else a path for the admin to complete."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import AccessLink

DEFAULT_EXPIRY_DAYS = 7          # an invitation
RESET_EXPIRY_DAYS = 1            # a password reset: handed over and used the same day


class LinkNotOpen(Exception):
    """Expired, revoked, used up, or unknown — the page shows the same plain refusal."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def mint(kind: str, *, created_by=None, user=None, expires_days: int | None = None,
         uses: int = 1, note: str = "") -> tuple[AccessLink, str]:
    if kind == AccessLink.RESET and user is None:
        raise ValueError("a password reset link needs the user it is for")
    if expires_days is None:
        expires_days = RESET_EXPIRY_DAYS if kind == AccessLink.RESET else DEFAULT_EXPIRY_DAYS
    token = secrets.token_urlsafe(32)
    link = AccessLink.objects.create(
        kind=kind, token_hash=_hash(token), user=user, created_by=created_by,
        expires_at=timezone.now() + timedelta(days=expires_days), uses_allowed=max(1, uses), note=note)
    return link, token


def path_for(kind: str, token: str) -> str:
    return f"/register/{token}" if kind == AccessLink.INVITE else f"/reset/{token}"


def url_for(kind: str, token: str) -> str:
    base = (getattr(settings, "BASE_URL", "") or "").rstrip("/")
    return base + path_for(kind, token)


def find_open(kind: str, token: str) -> AccessLink:
    """The open link for a token of this kind, else LinkNotOpen."""
    link = AccessLink.objects.filter(kind=kind, token_hash=_hash(token or "")).first()
    if link is None or not link.is_open:
        raise LinkNotOpen()
    return link


def spend(link: AccessLink) -> None:
    """Count one use, atomically against the limit; a link that just closed is refused."""
    with transaction.atomic():
        updated = (AccessLink.objects.filter(pk=link.pk, revoked_at__isnull=True, uses__lt=F("uses_allowed"),
                                             expires_at__gt=timezone.now())
                   .update(uses=F("uses") + 1))
    if not updated:
        raise LinkNotOpen()


def revoke(link: AccessLink) -> None:
    if not link.revoked_at:
        link.revoked_at = timezone.now()
        link.save(update_fields=["revoked_at"])


def end_other_sessions(user, keep_session_key: str | None = None) -> int:
    """Sign the user out everywhere but `keep_session_key`: the sessions are rows, and a
    row's user is inside its payload, so walk the live ones. Fine for a household."""
    from django.contrib.sessions.models import Session
    ended = 0
    for s in Session.objects.filter(expire_date__gte=timezone.now()):
        if s.session_key == keep_session_key:
            continue
        if s.get_decoded().get("_auth_user_id") == str(user.pk):
            s.delete()
            ended += 1
    return ended
