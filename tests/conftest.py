"""Test harness: a fresh SQLite data directory per test (the shared `database` handle is
re-pointed at it, ADR-0011 addendum; Django's connection too, since its tables share the
file) and a Django test client with the auth and CSRF gates off (`store_client`). Seeds
live in tests/dbhelper.py.

The per-test database is a copy of one template built once per session: the store's
schema files (`database.init()`) plus Django's migrations. Copying a file is milliseconds;
migrating per test is not."""

import shutil

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command
from django.db import connections


@pytest.fixture(autouse=True)
def _fresh_limiter():
    """The login rate limiter is process state: a test that fails a login five times must
    not lock the next test out."""
    from app.security import limiter
    limiter._user.clear(); limiter._ip.clear()


@pytest.fixture(autouse=True)
def _no_local_env(monkeypatch):
    """The suite never depends on the developer's .env: no SimpleFIN feed. Tests that
    want one set it on `app.config` themselves."""
    from app import config
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", "")


# --- Django's database is our file ------------------------------------------------------

@pytest.fixture(scope="session")
def django_db_setup():
    """pytest-django would create a test_* database; the file is ours (store_db)."""


@pytest.fixture(autouse=True)
def _unblock_django_db(django_db_blocker):
    with django_db_blocker.unblock():
        yield


def _point_django_at(path):
    conn = connections["default"]
    conn.close()
    conn.settings_dict["NAME"] = str(path)
    django_settings.DATABASES["default"]["NAME"] = str(path)


@pytest.fixture(scope="session")
def _template_db(tmp_path_factory, django_db_blocker):
    """money.sqlite with the store's schema AND Django's tables, built once."""
    from app.store.database import Database
    data = tmp_path_factory.mktemp("template") / "data"
    db = Database(data)
    db.init()
    with django_db_blocker.unblock():
        _point_django_at(db.path)
        call_command("migrate", verbosity=0, interactive=False)
        connections["default"].close()       # the last close checkpoints and removes the WAL
    return db.path


# --- SQLite store layer (app/store) ------------------------------------------------
# A fresh DATA_DIR per test; the shared `database` handle is re-pointed at it and the
# schema applied by the same init() production runs.

@pytest.fixture
def store_db(tmp_path, _template_db):
    from app.store import database
    previous = database.data_dir
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    shutil.copy(_template_db, data / "money.sqlite")
    database.configure(data)
    database.init()                          # nothing new to apply; enforces 0700/0600
    _point_django_at(database.path)
    try:
        yield database.data_dir
    finally:
        connections["default"].close()
        database.data_dir = previous


@pytest.fixture
def store_client(store_db, settings):
    """Django test client: the ledger seed (categories + transactions) written through the
    stores, auth and CSRF gates off (tests/test_security.py turns them on)."""
    from tests import dbhelper
    from tests.client import WebClient
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = False
    return WebClient()
