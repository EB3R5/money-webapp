"""`manage.py bootstrap_admin`: make sure someone can sign in (app/accounts.py
ensure_admin). The container entrypoint and the desktop launcher run it after `migrate`;
it is safe on every start."""

from django.core.management.base import BaseCommand

from app.accounts import ensure_admin


class Command(BaseCommand):
    help = "Create the default admin when no user exists."

    def handle(self, *args, **options):
        self.stdout.write(ensure_admin())
