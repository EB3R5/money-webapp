"""`manage.py invite [--days 7] [--uses 1] [--note "for Sam"]`: mint an invitation link and
print it once. The admin UI does the same under Access links."""

from django.core.management.base import BaseCommand

from app import links
from app.models import AccessLink


class Command(BaseCommand):
    help = "Mint an invitation link (shown once) for someone to join the household."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=links.DEFAULT_EXPIRY_DAYS)
        parser.add_argument("--uses", type=int, default=1)
        parser.add_argument("--note", default="")

    def handle(self, *args, **options):
        link, token = links.mint(AccessLink.INVITE, expires_days=options["days"], uses=options["uses"],
                                 note=options["note"])
        self.stdout.write(links.url_for(link.kind, token))
        self.stderr.write(f"expires {link.expires_at:%Y-%m-%d %H:%M} UTC, {link.uses_allowed} use(s); "
                          "revoke it in /admin/ under Access links")
