"""`manage.py reset_link <username> [--days 1]`: mint a one-time password reset link for a
user and print it once. The admin UI does the same under Access links (kind: Password reset)."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app import links
from app.models import AccessLink


class Command(BaseCommand):
    help = "Mint a one-time password reset link (shown once) for a user."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--days", type=int, default=links.RESET_EXPIRY_DAYS)

    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(username=options["username"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"no user {options['username']!r}")
        link, token = links.mint(AccessLink.RESET, user=user, expires_days=options["days"])
        self.stdout.write(links.url_for(link.kind, token))
        self.stderr.write(f"for {user.get_username()}, expires {link.expires_at:%Y-%m-%d %H:%M} UTC, one use; "
                          "revoke it in /admin/ under Access links")
