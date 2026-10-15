"""Minting, finding and revoking API tokens (app/models.py ApiToken). A token is
`mnt_<prefix><secret>`: the prefix is stored for the lookup, the whole token is hashed
(SHA-256) and the value is shown once."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from django.utils import timezone

from .models import ApiToken

PREFIX_LEN = 8


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def mint(user, name: str) -> tuple[ApiToken, str]:
    name = (name or "").strip()[:60] or "token"
    raw = "mnt_" + secrets.token_urlsafe(30)
    token = ApiToken.objects.create(user=user, name=name, prefix=raw[4:4 + PREFIX_LEN], key_hash=_hash(raw))
    return token, raw


def find_live(raw: str) -> ApiToken | None:
    """The live token behind a bearer value, else None (unknown, revoked, inactive user)."""
    if not raw or not raw.startswith("mnt_") or len(raw) < 4 + PREFIX_LEN:
        return None
    digest = _hash(raw)
    for t in ApiToken.objects.select_related("user").filter(prefix=raw[4:4 + PREFIX_LEN]):
        if hmac.compare_digest(t.key_hash, digest) and t.is_live:
            return t
    return None


def touch(token: ApiToken) -> None:
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())


def revoke(token: ApiToken) -> None:
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])
