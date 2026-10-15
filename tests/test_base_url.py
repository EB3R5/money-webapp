"""One public URL (config/settings.py from app/config.py BASE_URL): the request host Django
accepts, the origin its CSRF check trusts, what the bookmarklets and the links bake in.
CLIP_BASE_URL is the old name and still works, with a warning at start."""

import importlib
import logging

import pytest
from django.test import override_settings

from app import config
from tests.client import WebClient


def _settings_with(monkeypatch, **env):
    import config.settings as settings_module
    for k in ("BASE_URL", "CLIP_BASE_URL", "ALLOWED_HOSTS_EXTRA"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(config, "SESSION_SECRET", "x" * 64)
    importlib.reload(config)
    monkeypatch.setattr(config, "SESSION_SECRET", "x" * 64)
    return importlib.reload(settings_module)


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    yield
    import config.settings as settings_module
    for k in ("BASE_URL", "CLIP_BASE_URL", "ALLOWED_HOSTS_EXTRA"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(config); importlib.reload(settings_module)


def test_base_url_drives_hosts_origins_and_links(monkeypatch):
    s = _settings_with(monkeypatch, BASE_URL="https://money.example:8443/")
    assert "money.example" in s.ALLOWED_HOSTS and s.CSRF_TRUSTED_ORIGINS == ["https://money.example:8443"]
    assert s.BASE_URL == "https://money.example:8443"
    assert config.BASE_URL_FROM_LEGACY is False


def test_without_a_url_loopback_only(monkeypatch):
    s = _settings_with(monkeypatch)
    assert s.ALLOWED_HOSTS == ["127.0.0.1", "localhost", "money-next"] and s.CSRF_TRUSTED_ORIGINS == []
    assert s.BASE_URL == ""


def test_legacy_name_still_works_with_a_warning(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="money"):
        s = _settings_with(monkeypatch, CLIP_BASE_URL="https://old.example")
    assert s.BASE_URL == "https://old.example" and "old.example" in s.ALLOWED_HOSTS
    assert config.BASE_URL_FROM_LEGACY is True
    assert any("CLIP_BASE_URL is the old name" in r.getMessage() for r in caplog.records)
    s = _settings_with(monkeypatch, BASE_URL="https://new.example", CLIP_BASE_URL="https://old.example")
    assert s.BASE_URL == "https://new.example" and config.BASE_URL_FROM_LEGACY is False


def test_extra_hosts(monkeypatch):
    s = _settings_with(monkeypatch, ALLOWED_HOSTS_EXTRA="a.example, b.example")
    assert s.ALLOWED_HOSTS[-2:] == ["a.example", "b.example"]


def test_a_request_on_the_public_host_passes_the_host_check_and_csrf(store_db, settings):
    from tests import dbhelper
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = False
    with override_settings(ALLOWED_HOSTS=[*settings.ALLOWED_HOSTS, "money.example"],
                           CSRF_TRUSTED_ORIGINS=["https://money.example"], BASE_URL="https://money.example"):
        c = WebClient(enforce_csrf_checks=True, HTTP_HOST="money.example")
        import re
        page = c.get("/", secure=True)
        assert page.status_code == 200
        token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
        r = c.post("/api/transactions/category", json={"id": "t2", "value": "Auto"}, secure=True,
                   headers={"X-CSRF-Token": token, "Origin": "https://money.example"})
        assert r.status_code == 200
        assert "https://money.example/inventory/clip#" in c.get("/clippers", secure=True).text
