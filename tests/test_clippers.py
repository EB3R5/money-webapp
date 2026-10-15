"""The Clippers page: every bookmarklet, bound to the app origin (BASE_URL wins),
no inline handlers (CSP), and the legacy setup URL redirecting here."""

from app import config


def test_clippers_page_lists_every_bookmarklet(store_client):
    r = store_client.get("/clippers")
    assert r.status_code == 200
    assert "http://testserver/inventory/clip#" in r.text and "http://testserver/software/clip#" in r.text
    assert r.text.count("javascript:(function(){") >= 4          # two buttons + two paste boxes
    assert "Clip → Inventory" in r.text and "Clip → Software" in r.text
    assert "onclick=" not in r.text
    assert 'href="/clippers">Clippers</a>' in r.text and "/inventory/clip/setup" not in r.text


def test_base_url_overrides_the_request_origin(store_client, monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "https://money.example")
    from django.conf import settings as dj
    monkeypatch.setattr(dj, "BASE_URL", "https://money.example")
    r = store_client.get("/clippers")
    assert "https://money.example/software/clip#" in r.text and "http://testserver/" not in r.text


def test_legacy_setup_url_redirects(store_client):
    r = store_client.get("/inventory/clip/setup")
    assert r.status_code == 302 and r.headers["location"] == "/clippers"


def test_routes_registered():
    from app.urls import VIEW_MODULES
    from app.views import clippers, inventory_clip
    from tests.dbhelper import routes
    assert clippers in VIEW_MODULES
    assert "/clippers" in routes(clippers) and "/inventory/clip/setup" in routes(inventory_clip)
