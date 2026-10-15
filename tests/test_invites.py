"""Invitation links (app/links.py, app/models.py AccessLink, app/views/auth.py register_view):
the only way to sign up. An admin mints a link (hashed in the database, shown once); the
page it opens creates a regular member; expiry, a use count and revocation close it; a
closed or unknown link is a plain 404, never a form."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from app import links
from app.models import AccessLink
from app.security import limiter
from tests import dbhelper
from tests.client import WebClient

GOOD = "a-long-enough-password-1"


@pytest.fixture
def site(store_db, settings):
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    settings.BASE_URL = "https://money.example"
    limiter._user.clear(); limiter._ip.clear()
    admin = get_user_model().objects.create_superuser("admin", password=GOOD)
    return admin


def test_mint_stores_a_hash_and_builds_the_link(site):
    link, token = links.mint(AccessLink.INVITE, created_by=site, note="for Sam")
    assert len(token) >= 40 and token not in link.token_hash and len(link.token_hash) == 64
    assert link.state == "open" and link.uses_allowed == 1 and link.created_by == site
    assert links.url_for(link.kind, token) == f"https://money.example/register/{token}"
    assert (link.expires_at - timezone.now()).days in (6, 7)


def test_command_prints_the_link_once(site, capsys):
    call_command("invite", "--days", "2", "--uses", "3", "--note", "family")
    out, err = capsys.readouterr()
    assert out.strip().startswith("https://money.example/register/") and "3 use(s)" in err
    link = AccessLink.objects.get()
    assert link.uses_allowed == 3 and link.note == "family" and (link.expires_at - timezone.now()).days in (1, 2)


def test_register_creates_a_member_and_signs_them_in(site):
    _, token = links.mint(AccessLink.INVITE, created_by=site)
    c = WebClient()
    page = c.get(f"/register/{token}")
    assert page.status_code == 200 and "You have been invited" in page.text and f'action="/register/{token}"' in page.text
    r = c.post(f"/register/{token}", data={"username": "sam", "password1": GOOD, "password2": GOOD})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert c.get("/").status_code == 200                       # signed in, the household's ledger
    sam = get_user_model().objects.get(username="sam")
    assert not sam.is_staff and not sam.is_superuser
    assert c.get("/admin/").status_code == 302                  # a member, not an admin
    link = AccessLink.objects.get()
    assert link.uses == 1 and link.state == "used"
    assert c.get(f"/register/{token}").status_code == 404        # one use, spent


def test_closed_or_unknown_links_are_a_plain_404(site):
    c = WebClient()
    r = c.get("/register/not-a-token")
    assert r.status_code == 404 and "no longer valid" in r.text and "<form" not in r.text
    _, expired = links.mint(AccessLink.INVITE, expires_days=0)
    assert c.get(f"/register/{expired}").status_code == 404
    link, revoked = links.mint(AccessLink.INVITE)
    links.revoke(link)
    assert c.get(f"/register/{revoked}").status_code == 404
    assert c.post(f"/register/{revoked}", data={"username": "x", "password1": GOOD, "password2": GOOD}).status_code == 404
    assert get_user_model().objects.count() == 1
    # a reset link's token never opens the register page
    _, reset = links.mint(AccessLink.RESET, user=site)
    assert c.get(f"/register/{reset}").status_code == 404


def test_use_count_is_enforced_atomically(site):
    link, token = links.mint(AccessLink.INVITE, uses=2)
    links.spend(link); links.spend(link)
    with pytest.raises(links.LinkNotOpen):
        links.spend(link)
    link.refresh_from_db()
    assert link.uses == 2 and link.state == "used"


def test_register_validates_counts_failures_and_refuses_a_taken_name(site):
    _, token = links.mint(AccessLink.INVITE, uses=5)
    c = WebClient()
    r = c.post(f"/register/{token}", data={"username": "Admin", "password1": GOOD, "password2": GOOD})
    assert r.status_code == 400 and "taken" in r.text
    r = c.post(f"/register/{token}", data={"username": "sam", "password1": "short", "password2": "short"})
    assert r.status_code == 400 and "too short" in r.text and 'value="sam"' in r.text
    assert AccessLink.objects.get().uses == 0                   # a failed attempt spends nothing
    for _ in range(3):
        c.post(f"/register/{token}", data={"username": "sam", "password1": "short", "password2": "short"})
    r = c.post(f"/register/{token}", data={"username": "sam", "password1": GOOD, "password2": GOOD})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_register_over_https_with_csrf_enforced(site):
    _, token = links.mint(AccessLink.INVITE)
    c = WebClient(enforce_csrf_checks=True)
    page = c.get(f"/register/{token}", secure=True)
    import re
    csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text).group(1)
    assert c.post(f"/register/{token}", data={"username": "sam", "password1": GOOD, "password2": GOOD},
                  secure=True, headers={"Origin": "https://testserver"}).status_code == 403
    r = c.post(f"/register/{token}", data={"csrfmiddlewaretoken": csrf, "username": "sam", "password1": GOOD,
                                            "password2": GOOD}, secure=True, headers={"Origin": "https://testserver"})
    assert r.status_code == 303 and c.get("/", secure=True).status_code == 200


def test_admin_mints_and_revokes_links(site):
    c = WebClient()
    c.django.force_login(site)
    add = c.get("/admin/money/accesslink/add/")
    assert add.status_code == 200
    import re
    csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', add.text).group(1)
    r = c.post("/admin/money/accesslink/add/", data={"csrfmiddlewaretoken": csrf, "kind": "invite", "note": "for Sam",
                                                     "expires_at_0": "2030-01-01", "expires_at_1": "12:00:00",
                                                     "uses_allowed": "1"}, follow_redirects=True)
    assert r.status_code == 200 and "copy it now" in r.text and "https://money.example/register/" in r.text
    link = AccessLink.objects.get()
    assert link.created_by == site and link.state == "open" and link.expires_at.year == 2030
    token = re.search(r"/register/([A-Za-z0-9_-]+)", r.text).group(1)
    assert WebClient().get(f"/register/{token}").status_code == 200
    r = c.post("/admin/money/accesslink/", data={"csrfmiddlewaretoken": csrf, "action": "revoke", "_selected_action": str(link.pk)},
               follow_redirects=True)
    assert r.status_code == 200
    link.refresh_from_db()
    assert link.state == "revoked" and WebClient().get(f"/register/{token}").status_code == 404
