"""What this app stores through Django's ORM: only what Django itself needs beside
`django.contrib.auth` (ADR-0024). Everything about money lives in the hand-written stores.

Profile: one row per user, created on demand. `must_change_password` is set on the account
`bootstrap_admin` seeds from DEFAULT_USER / DEFAULT_PASSWORD and cleared the first time that
password is changed; the auth gate sends a flagged user to /account until then."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    must_change_password = models.BooleanField(default=False)

    class Meta:
        db_table = "money_profile"

    def __str__(self):
        return f"profile of {self.user.get_username()}"


class AccessLink(models.Model):
    """A link that lets someone in, minted by an admin and handed over by hand (the app
    sends no email): an **invitation** (the recipient registers and joins the household) or,
    later, a **password reset** for one user. The database holds only a hash of the token;
    the link itself is shown once, when minted. Expiry, a use count and revocation bound it."""

    INVITE, RESET = "invite", "reset"
    KINDS = [(INVITE, "Invitation"), (RESET, "Password reset")]

    kind = models.CharField(max_length=8, choices=KINDS, default=INVITE)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="access_links", help_text="The user a reset link is for; empty for an invitation.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="minted_links", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    uses_allowed = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)
    note = models.CharField(max_length=120, blank=True, help_text="Who it is for, for your own eyes.")

    class Meta:
        db_table = "money_accesslink"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.note or self.pk} ({self.state})"

    @property
    def state(self) -> str:
        if self.revoked_at:
            return "revoked"
        if self.expires_at is None:          # the admin's add form, before the mint
            return "new"
        if self.expires_at <= timezone.now():
            return "expired"
        if self.uses >= self.uses_allowed:
            return "used"
        return "open"

    @property
    def is_open(self) -> bool:
        return self.state == "open"


class ApiToken(models.Model):
    """A per-user bearer token for scripts and agents (Mealie-style): named, minted on the
    account page or by `manage.py api_token`, shown once, revocable. The database holds the
    token's hash and an 8-character prefix for the lookup; a request carrying
    `Authorization: Bearer <token>` is that user, is exempt from the CSRF check, and never
    gets a session (app/middleware.py ApiTokenMiddleware)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField(max_length=60)
    prefix = models.CharField(max_length=8, db_index=True, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        db_table = "money_apitoken"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…) of {self.user.get_username()}"

    @property
    def is_live(self) -> bool:
        return self.revoked_at is None and self.user.is_active
