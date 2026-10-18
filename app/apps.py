"""The Django app config. ready() does the two things every process needs before touching
the store: a private umask and the shared database handle pointed at DATA_DIR. Schema
application is a command (`manage.py init_store`), run by the container entrypoint and the
launcher, never implicitly on import."""

from django.apps import AppConfig


class MoneyConfig(AppConfig):
    name = "app"
    label = "money"
    verbose_name = "Passbook"

    def ready(self):
        from .config import DATA_DIR
        from .store import database, permissions
        permissions.apply_umask()
        database.configure(DATA_DIR)
