"""Chart colours (app/chart_colors.py, app/views/settings_appearance.py): six series colours
per user, kept on the Profile as overrides, put on <html> as --chart-* tokens on every page,
edited on the Dashboard's folded panel or Settings → Appearance."""

import pytest
from django.contrib.auth import get_user_model

from app import chart_colors
from app.models import Profile
from tests.client import WebClient


@pytest.fixture
def user_client(store_client):
    """A signed-in member: the panel saves against a real user."""
    user = get_user_model().objects.create_user("pat", password="hunter2-hunter2-")
    c = WebClient()
    c._c.force_login(user)
    return c, user


def test_defaults_and_normalise():
    assert chart_colors.for_user(None) == chart_colors.DEFAULTS
    assert chart_colors.normalise({"net": "#4F6B8C", "income": " #112233 ", "spend": ""}) == {"income": "#112233"}
    with pytest.raises(ValueError, match="s4"):
        chart_colors.normalise({"s4": "red"})
    with pytest.raises(ValueError):
        chart_colors.normalise({"spend": "#12345"})
    assert chart_colors.normalise({"bogus": "#123456"}) == {}      # unknown roles are ignored


def test_every_page_carries_the_tokens_and_the_dashboard_the_panel(user_client):
    client, user = user_client
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "--chart-net: #4f6b8c;" in r.text and "--chart-s6: #5c6670;" in r.text
    assert '<details class="chart-colours card" id="chart-colours">' in r.text          # folded on the Dashboard
    assert 'name="next" value="/dashboard"' in r.text
    assert "chart-colours.js" in r.text
    r = client.get("/settings/appearance")
    assert r.status_code == 200
    assert '<details class="chart-colours card" id="chart-colours" open>' in r.text     # open in Settings
    assert "Income bars" in r.text and "Reset to defaults" in r.text
    assert 'href="/settings/appearance"' in r.text                                    # the nav link


def test_save_reset_and_reject(user_client):
    client, user = user_client
    r = client.post("/settings/appearance/chart-colours",
                    data={"net": "#112233", "income": "#2f6b4f", "spend": "#AABBCC", "next": "/dashboard"})
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    assert Profile.objects.get(user=user).chart_colors == {"net": "#112233", "spend": "#aabbcc"}   # defaults not stored
    r = client.get("/dashboard")
    assert "--chart-net: #112233;" in r.text and "--chart-spend: #aabbcc;" in r.text and "--chart-income: #2f6b4f;" in r.text
    assert 'value="#112233"' in r.text                                                 # the panel shows the saved value

    # another member keeps the defaults: the choice is per account
    other = get_user_model().objects.create_user("sam", password="hunter2-hunter2-")
    assert chart_colors.for_user(other) == chart_colors.DEFAULTS

    r = client.post("/settings/appearance/chart-colours", data={"net": "not a colour", "next": "/dashboard"})
    assert r.status_code == 400 and "not a colour" in r.text and "is not a colour like" in r.text
    assert chart_colors.for_user(user)["net"] == "#112233"                            # nothing changed

    r = client.post("/settings/appearance/chart-colours", data={"reset": "1", "net": "#000000", "next": "https://evil.test/x"})
    assert r.status_code == 303 and r.headers["location"] == "/settings/appearance"    # off-site next ignored
    assert Profile.objects.get(user=user).chart_colors == {}
    assert chart_colors.for_user(user) == chart_colors.DEFAULTS


def test_anonymous_gets_defaults_and_cannot_save(store_db, settings):
    settings.MONEY_AUTH_GATE = True
    r = WebClient().post("/settings/appearance/chart-colours", data={"net": "#112233"})
    assert r.status_code in (302, 303, 401, 403)
    assert not Profile.objects.exclude(chart_colors={}).exists()
