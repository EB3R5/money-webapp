"""Admin-generated password reset links (app/links.py kind reset, app/views/auth.py
reset_view): the app sends no email, so an admin mints a one-time link and hands it over;
the page sets a new password, spends the link, ends the user's other sessions, signs them
in. A closed or unknown link is a plain 404; the login page says to ask your admin."""

import re

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from app import accounts, links
from app.models import AccessLink
from app.security import limiter
from tests import dbhelper
from tests.client import WebClient

GOOD = "a-long-enough-password-1"
NEW = "another-long-enough-password-2"


@pytest.fixture
def site(store_db, settings):
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    settings.BASE_URL = "https://money.example"
    limiter._user.clear(); limiter._ip.clear()
    admin = get_user_model().objects.create_superuser("admin", password=GOOD)
    sam = get_user_model().objects.create_user("sam", password=GOOD)
    return admin, sam


def test_mint_needs_a_user_and_expires_in_a_day(site):
    admin, sam = site
    with pytest.raises(ValueError):
        links.mint(AccessLink.RESET)
    link, token = links.mint(AccessLink.RESET, user=sam, created_by=admin)
    assert link.user == sam and link.uses_allowed == 1
    assert 0 <= (link.expires_at - link.created_at).total_seconds() / 3600 <= 24.01
    assert links.url_for(link.kind, token) == f"https://money.example/reset/{token}"


def test_command_prints_the_link_once_and_knows_its_user(site, capsys):
    call_command("reset_link", "sam")
    out, err = capsys.readouterr()
    assert out.strip().startswith("https://money.example/reset/") and "for sam" in err
    with pytest.raises(Exception, match="no user"):
        call_command("reset_link", "nobody")


def test_reset_sets_the_password_ends_other_sessions_and_signs_in(site):
    admin, sam = site
    other = WebClient()                                            # sam's laptop, signed in
    assert other.post("/login", data={"username": "sam", "password": GOOD}).status_code == 303
    assert other.get("/").status_code == 200
    accounts.set_must_change(sam, True)                            # a flag, if one was set, clears too
    _, token = links.mint(AccessLink.RESET, user=sam, created_by=admin)
    phone = WebClient()
    page = phone.get(f"/reset/{token}")
    assert page.status_code == 200 and "<strong>sam</strong>" in page.text and f'action="/reset/{token}"' in page.text
    r = phone.post(f"/reset/{token}", data={"password1": NEW, "password2": NEW})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert phone.get("/").status_code == 200                        # signed in here
    assert other.get("/").status_code == 303                        # signed out there
    sam.refresh_from_db()
    assert sam.check_password(NEW) and not sam.check_password(GOOD)
    assert not accounts.must_change_password(sam)
    assert AccessLink.objects.get().state == "used"
    assert phone.get(f"/reset/{token}").status_code == 404           # one use


def test_closed_unknown_or_wrong_kind_is_a_plain_404(site):
    admin, sam = site
    c = WebClient()
    r = c.get("/reset/nope")
    assert r.status_code == 404 and "no longer valid" in r.text and "<form" not in r.text
    _, invite = links.mint(AccessLink.INVITE)
    assert c.get(f"/reset/{invite}").status_code == 404              # an invitation never resets a password
    link, revoked = links.mint(AccessLink.RESET, user=sam)
    links.revoke(link)
    assert c.get(f"/reset/{revoked}").status_code == 404
    _, expired = links.mint(AccessLink.RESET, user=sam, expires_days=0)
    assert c.post(f"/reset/{expired}", data={"password1": NEW, "password2": NEW}).status_code == 404
    sam.is_active = False; sam.save()
    _, inactive = links.mint(AccessLink.RESET, user=sam)
    assert c.get(f"/reset/{inactive}").status_code == 404


def test_reset_validates_counts_failures_and_forgives_the_lockout(site):
    admin, sam = site
    for _ in range(5):                                               # sam locked themself out
        WebClient().post("/login", data={"username": "sam", "password": "wrong"})
    assert WebClient().post("/login", data={"username": "sam", "password": GOOD}).status_code == 429
    _, token = links.mint(AccessLink.RESET, user=sam)
    c = WebClient()
    r = c.post(f"/reset/{token}", data={"password1": "short", "password2": "short"})
    assert r.status_code == 400 and "too short" in r.text
    r = c.post(f"/reset/{token}", data={"password1": NEW, "password2": NEW + "x"})
    assert r.status_code == 400 and "do not match" in r.text
    assert AccessLink.objects.get().uses == 0
    assert c.post(f"/reset/{token}", data={"password1": NEW, "password2": NEW}).status_code == 303
    c.post("/logout")
    assert WebClient().post("/login", data={"username": "sam", "password": NEW}).status_code == 303   # lockout forgiven
    _, token2 = links.mint(AccessLink.RESET, user=sam)
    for _ in range(5):                                               # five bad tries on an open link
        assert WebClient().post(f"/reset/{token2}", data={"password1": "x", "password2": "y"}).status_code == 400
    r = WebClient().post(f"/reset/{token2}", data={"password1": NEW, "password2": NEW})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_reset_over_https_with_csrf_enforced(site):
    admin, sam = site
    _, token = links.mint(AccessLink.RESET, user=sam)
    c = WebClient(enforce_csrf_checks=True)
    csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', c.get(f"/reset/{token}", secure=True).text).group(1)
    assert c.post(f"/reset/{token}", data={"password1": NEW, "password2": NEW}, secure=True,
                  headers={"Origin": "https://testserver"}).status_code == 403
    r = c.post(f"/reset/{token}", data={"csrfmiddlewaretoken": csrf, "password1": NEW, "password2": NEW},
               secure=True, headers={"Origin": "https://testserver"})
    assert r.status_code == 303


def test_login_page_says_ask_your_admin(site):
    assert "Ask your admin for a reset link" in WebClient().get("/login").text


def test_admin_add_form_insists_on_a_user_for_a_reset(site):
    admin, sam = site
    c = WebClient()
    c.django.force_login(admin)
    csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', c.get("/admin/money/accesslink/add/").text).group(1)
    r = c.post("/admin/money/accesslink/add/", data={"csrfmiddlewaretoken": csrf, "kind": "reset", "note": "",
                                                     "expires_at_0": "2030-01-01", "expires_at_1": "12:00:00", "uses_allowed": "1"})
    assert r.status_code == 200 and "needs the user" in r.text and not AccessLink.objects.exists()
    r = c.post("/admin/money/accesslink/add/", data={"csrfmiddlewaretoken": csrf, "kind": "reset", "user": str(sam.pk), "note": "",
                                                     "expires_at_0": "2030-01-01", "expires_at_1": "12:00:00", "uses_allowed": "1"},
               follow_redirects=True)
    assert r.status_code == 200 and "https://money.example/reset/" in r.text
    token = re.search(r"/reset/([A-Za-z0-9_-]+)", r.text).group(1)
    assert WebClient().get(f"/reset/{token}").status_code == 200
