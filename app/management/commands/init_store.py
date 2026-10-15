"""`manage.py init_store`: create the data directory, apply every schema file newer than the
recorded version (app/store/database.py), and give a fresh database its starter taxonomies —
ledger, account and inventory categories (app/starter.py; a table with any row is never touched). The container entrypoint and
the desktop launcher run it before `migrate`; it is safe on every start."""

from django.core.management.base import BaseCommand

from app.starter import seed_all
from app.store import database


class Command(BaseCommand):
    help = "Create the data directory, apply the store's schema files, seed a fresh database."

    def handle(self, *args, **options):
        version = database.init()
        self.stdout.write(f"store schema at version {version} ({database.path})")
        for what, seeded in seed_all().items():
            if seeded:
                self.stdout.write(f"fresh database: {seeded} starter {what} written")
