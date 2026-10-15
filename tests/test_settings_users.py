"""Settings → Users (app/views/settings_users.py): admins see the members, the open
invitations and the pending reset links, and mint, revoke, deactivate and promote from the
page; every action lands in the admin log; the last admin cannot be removed."""

import re

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model

from app import links
from app.models import AccessLink
from tests import dbhelper
from tests.client import WebClient

GOOD = "a-long-enough-password-1"


@pytest.fixture
def site(store_db, settings):
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    settings.BASE_URL = "https://money.example"
    admin = get_user_model().objects.create_superuser("admin", password=GOOD)
    sam = get_user_model().objects.create_user("sam", password=GOOD)
    c = WebClient()
    c.django.force_login(admin)
    return c, admin, sam


def test_members_only_see_a_403_and_no_menu_entry(site):
    c, admin, sam = site
    m = WebClient()
    m.django.force_login(sam)
    r = m.get("/settings/users")
    assert r.status_code == 403 and "Admins only" in r.text
    assert m.post("/settings/users/invite", data={"note": "x"}).status_code == 403
    assert 'href="/settings/users"' not in m.get("/").text
    assert 'href="/settings/users"' in c.get("/").text


def test_page_lists_members_invites_and_resets(site):
    c, admin, sam = site
    links.mint(AccessLink.INVITE, created_by=admin, note="for Pat", uses=3)
    links.mint(AccessLink.RESET, created_by=admin, user=sam)
    spent, _ = links.mint(AccessLink.INVITE, note="zzz-revoked")
    links.revoke(spent)
    r = c.get("/settings/users")
    assert r.status_code == 200
    assert "admin" in r.text and "(you)" in r.text and "sam" in r.text and "member" in r.text
    assert "for Pat" in r.text and "3 use(s) left" in r.text and "zzz-revoked" not in r.text   # open links only
    assert "Password reset links" in r.text and "minted by admin" in r.text


def test_mint_invite_and_reset_show_the_link_once_and_log_it(site):
    c, admin, sam = site
    r = c.post("/settings/users/invite", data={"note": "Pat", "days": "3", "uses": "2"})
    assert r.status_code == 200 and "copy it now" in r.text
    url = re.search(r"https://money\.example/register/[A-Za-z0-9_-]+", r.text).group(0)
    link = AccessLink.objects.get(kind="invite")
    assert link.note == "Pat" and link.uses_allowed == 2 and link.created_by == admin
    assert WebClient().get(url.replace("https://money.example", "")).status_code == 200
    assert url not in c.get("/settings/users").text                                    # shown once
    r = c.post("/settings/users/reset", data={"user_id": sam.pk})
    assert r.status_code == 200 and "password reset link for <strong>sam</strong>" in r.text
    assert "/reset/" in r.text
    assert c.post("/settings/users/reset", data={"user_id": 999}).status_code == 404
    assert c.post("/settings/users/invite", data={"days": "x"}).status_code == 400
    msgs = list(LogEntry.objects.values_list("change_message", flat=True))
    assert any("minted invitation Pat" in m for m in msgs) and any("reset link for sam" in m for m in msgs)


def test_revoke_from_the_page(site):
    c, admin, sam = site
    link, token = links.mint(AccessLink.INVITE, note="Pat")
    r = c.post(f"/settings/users/links/{link.pk}/revoke")
    assert r.status_code == 303 and r.headers["location"] == "/settings/users"
    link.refresh_from_db()
    assert link.state == "revoked" and WebClient().get(f"/register/{token}").status_code == 404
    assert c.post("/settings/users/links/999/revoke").status_code == 404


def test_deactivate_reactivate_and_the_last_admin_rule(site):
    c, admin, sam = site
    other = WebClient()
    other.post("/login", data={"username": "sam", "password": GOOD})
    assert other.get("/").status_code == 200
    r = c.post(f"/settings/users/{sam.pk}/active", data={"active": "0"})
    assert r.status_code == 303
    sam.refresh_from_db()
    assert not sam.is_active and other.get("/").status_code == 303                       # signed out everywhere
    assert WebClient().post("/login", data={"username": "sam", "password": GOOD}).status_code == 401
    assert "deactivated" in c.get("/settings/users").text
    c.post(f"/settings/users/{sam.pk}/active", data={"active": "1"})
    sam.refresh_from_db()
    assert sam.is_active
    r = c.post(f"/settings/users/{admin.pk}/active", data={"active": "0"})
    assert r.status_code == 400 and "last admin" in r.text
    admin.refresh_from_db()
    assert admin.is_active
    assert any("deactivated the member" in m for m in LogEntry.objects.values_list("change_message", flat=True))


def test_make_admin_and_make_member_with_the_last_admin_rule(site):
    c, admin, sam = site
    r = c.post(f"/settings/users/{admin.pk}/admin", data={"admin": "0"})
    assert r.status_code == 400 and "last admin" in r.text
    assert c.post(f"/settings/users/{sam.pk}/admin", data={"admin": "1"}).status_code == 303
    sam.refresh_from_db()
    assert sam.is_superuser and sam.is_staff
    assert c.post(f"/settings/users/{admin.pk}/admin", data={"admin": "0"}).status_code == 303   # now allowed
    admin.refresh_from_db()
    assert not admin.is_superuser and not admin.is_staff
    assert c.get("/settings/users").status_code == 403                                   # no longer an admin
