"""Data directory permissions (app/store/permissions.py) and the startup guards: the
directory is 0700 and the database 0600 after init(), a lax mode is tightened and logged,
an unfixable one refuses to start, the process umask is 077 (app/apps.py ready()), and an
empty SESSION_SECRET refuses to serve (config/settings.py)."""

import logging
import os
import stat

import pytest

from app.store import database, permissions

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_fresh_init_creates_dir_700_and_db_600(store_db):
    assert _mode(store_db) == 0o700
    assert _mode(database.path) == 0o600


def test_lax_modes_are_fixed_and_logged(store_db, caplog):
    os.chmod(store_db, 0o755)
    os.chmod(database.path, 0o644)
    wal = database.path.with_name(database.path.name + "-wal")
    wal.write_bytes(b"")
    os.chmod(wal, 0o644)
    with caplog.at_level(logging.WARNING, logger="money.store"):
        database.init()
    assert _mode(store_db) == 0o700
    assert _mode(database.path) == 0o600
    assert not wal.exists() or _mode(wal) == 0o600   # SQLite removes an empty WAL on close
    msgs = [r.getMessage() for r in caplog.records if "permissions tightened" in r.getMessage()]
    assert any("money.sqlite: 0644 -> 0600" in m for m in msgs)
    assert any("data: 0755 -> 0700" in m for m in msgs)
    assert any("money.sqlite-wal: 0644 -> 0600" in m for m in msgs)


def test_already_private_makes_no_fix(store_db):
    assert permissions.ensure_private(store_db, database.path) == []


def test_unfixable_database_refuses_to_start(store_db, monkeypatch):
    os.chmod(database.path, 0o644)

    def deny(path, mode):
        raise PermissionError("Operation not permitted")
    monkeypatch.setattr(os, "chmod", deny)
    with pytest.raises(permissions.InsecureDataDir, match="readable by other users"):
        database.init()


def test_filesystem_that_ignores_chmod_refuses(store_db, monkeypatch):
    os.chmod(database.path, 0o644)
    monkeypatch.setattr(os, "chmod", lambda path, mode: None)   # a mount that keeps 0644
    with pytest.raises(permissions.InsecureDataDir, match="does not keep permissions"):
        database.ensure_private()


def test_umask_is_077():
    before = os.umask(0o022)
    try:
        assert permissions.apply_umask() == 0o022
        assert os.umask(0o022) == 0o077
    finally:
        os.umask(before)


def test_settings_refuse_an_empty_session_secret(monkeypatch, tmp_path):
    import importlib
    from django.core.exceptions import ImproperlyConfigured
    from app import config
    import config.settings as settings_module
    monkeypatch.setattr(config, "SESSION_SECRET", "")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    with pytest.raises(ImproperlyConfigured, match="SESSION_SECRET is empty"):
        importlib.reload(settings_module)
    assert not (tmp_path / "data").exists(), "refused before touching the data directory"
    monkeypatch.setattr(config, "SESSION_SECRET", "x" * 64)
    importlib.reload(settings_module)         # leave the module as the suite found it


def test_init_store_creates_a_private_data_dir_under_umask_077(tmp_path):
    from django.core.management import call_command
    from app.store import database as handle
    previous = handle.data_dir
    before = os.umask(0o022)
    try:
        permissions.apply_umask()             # what app/apps.py ready() did at startup
        handle.configure(tmp_path / "served")
        call_command("init_store", verbosity=0)
        assert os.umask(0o077) == 0o077
        assert _mode(tmp_path / "served") == 0o700
        assert _mode(tmp_path / "served" / "money.sqlite") == 0o600
    finally:
        os.umask(before)
        handle.data_dir = previous
