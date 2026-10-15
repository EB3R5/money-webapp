"""Settings → Feed (app/views/settings_feed.py): the SimpleFIN state on one page, the claim
instructions when it is off, never the credential."""

from datetime import UTC, datetime

import httpx

from app import config
from app.simplefin import sync as sf
from app.simplefin.client import SimpleFinClient
from app.views import settings_feed
from tests.test_simplefin_sync import ACCESS, payload


def test_unconfigured_page_explains_the_claim(store_client, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", "")
    r = store_client.get("/settings/feed")
    assert r.status_code == 200
    assert "not configured" in r.text and "python -m app.simplefin.claim --stdin" in r.text
    assert "SIMPLEFIN_ACCESS_URL" in r.text and "Next scheduled run" not in r.text
    assert settings_feed.next_scheduled_run() is None


def test_configured_page_shows_state_and_never_the_credential(store_client, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", ACCESS)
    monkeypatch.setattr(config, "SYNC_INTERVAL_HOURS", 6)
    monkeypatch.setattr(config, "SYNC_CRON_MINUTE", 17)
    c = SimpleFinClient(ACCESS, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload())))
    s = sf.run_sync(client=c, now=datetime.now(UTC), trigger="manual")     # today, so the budget line counts it
    assert s.status == "ok"
    r = store_client.get("/settings/feed")
    assert r.status_code == 200
    st = sf.status(datetime.now(UTC))
    assert st["requests_used_today"] >= 1                       # the run above, however many chunks it took
    assert "configured" in r.text and "Requests today" in r.text
    assert f"{st['requests_used_today']} of {st['budget']}" in r.text
    assert "pill-ok" in r.text and "trigger manual" in r.text and "window end" in r.text
    assert "Next scheduled run" in r.text and "every 6 h at :17" in r.text
    assert ACCESS not in r.text and "u:p@" not in r.text and "bridge.test" not in r.text   # never the secret
    nxt = settings_feed.next_scheduled_run(datetime(2026, 1, 1, 5, 0, tzinfo=UTC))
    assert nxt == datetime(2026, 1, 1, 6, 17, tzinfo=UTC)


def test_linked_from_the_nav_and_the_activity_page(store_client, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", "")
    html = store_client.get("/activity").text
    assert 'href="/settings/feed"' in html and "<summary>Settings</summary>" in html
