"""`manage.py api_token <username> --name "clipper script"`: mint an API token for a user
and print it once. The account page does the same."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app import tokens


class Command(BaseCommand):
    help = "Mint a per-user API token (shown once) for a script or an agent."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", required=True)

    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(username=options["username"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"no user {options['username']!r}")
        token, raw = tokens.mint(user, options["name"])
        self.stdout.write(raw)
        self.stderr.write(f"token {token.name!r} ({token.prefix}…) for {user.get_username()}; "
                          "send it as `Authorization: Bearer <token>`; revoke it on /account")
