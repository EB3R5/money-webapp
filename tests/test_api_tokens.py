"""Per-user API tokens (app/tokens.py, app/models.py ApiToken, app/middleware.py
ApiTokenMiddleware, the /account page): a named bearer token, shown once, hashed; a
request carrying it is that user, needs no session or CSRF token, never gets a session;
unknown or revoked tokens are 401 at once. The software import endpoint is the first
consumer."""

import re

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from app import accounts, tokens
from app.models import ApiToken
from tests import dbhelper
from tests.client import WebClient

GOOD = "a-long-enough-password-1"
RUN = {"host": "h", "managers": [], "entries": []}


@pytest.fixture
def site(store_db, settings):
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    return get_user_model().objects.create_user("sam", password=GOOD)


def test_mint_shows_once_and_stores_a_hash(site):
    token, raw = tokens.mint(site, "clipper script")
    assert raw.startswith("mnt_") and len(raw) > 40
    assert token.prefix == raw[4:12] and raw not in token.key_hash and len(token.key_hash) == 64
    assert tokens.find_live(raw) == token
    assert tokens.find_live(raw[:-1] + ("a" if raw[-1] != "a" else "b")) is None
    assert tokens.find_live("nope") is None and tokens.find_live("") is None


def test_bearer_authenticates_without_session_or_csrf_and_the_import_is_the_first_consumer(site):
    _, raw = tokens.mint(site, "importer")
    c = WebClient(enforce_csrf_checks=True)                      # a script: no cookie, no CSRF token
    r = c.post("/api/software/import", json=RUN, headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert "money_session" not in r.cookies                      # never a session
    assert c.get("/api/transactions/doc/t1", headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    assert c.get("/api/transactions/doc/t1").status_code == 401  # the token was per request, nothing stuck
    assert ApiToken.objects.get().last_used_at is not None


def test_unknown_revoked_or_inactive_tokens_are_401_and_never_fall_through(site):
    c = WebClient()
    c.django.force_login(site)                                   # even with a live session...
    assert c.get("/api/transactions/doc/t1").status_code == 200
    r = c.get("/api/transactions/doc/t1", headers={"Authorization": "Bearer mnt_notatoken0000000000000000"})
    assert r.status_code == 401 and r.json() == {"detail": "Not authenticated"}   # ...a bad bearer is refused
    token, raw = tokens.mint(site, "x")
    tokens.revoke(token)
    assert WebClient().get("/api/transactions/doc/t1", headers={"Authorization": f"Bearer {raw}"}).status_code == 401
    token2, raw2 = tokens.mint(site, "y")
    site.is_active = False; site.save()
    assert WebClient().get("/api/transactions/doc/t1", headers={"Authorization": f"Bearer {raw2}"}).status_code == 401
    assert WebClient().get("/api/transactions/doc/t1", headers={"Authorization": "Bearer anything"}).status_code == 401


def test_a_flagged_user_s_token_still_hits_the_forced_change(site):
    accounts.set_must_change(site, True)
    _, raw = tokens.mint(site, "x")
    r = WebClient().get("/api/transactions/doc/t1", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 403 and r.json() == {"detail": "Password change required"}


def test_account_page_mints_lists_and_revokes(site):
    c = WebClient()
    c.django.force_login(site)
    page = c.get("/account")
    assert page.status_code == 200 and "No tokens yet" in page.text
    r = c.post("/account/tokens", data={"name": "software import script"})
    assert r.status_code == 200 and "copy it now" in r.text
    raw = re.search(r"<pre class=\"token-value\">(mnt_[A-Za-z0-9_-]+)</pre>", r.text).group(1)
    assert tokens.find_live(raw) is not None
    page = c.get("/account")
    assert "software import script" in page.text and raw not in page.text        # shown once
    assert c.post("/account/tokens", data={"name": ""}).status_code == 400
    token = ApiToken.objects.get()
    assert c.post(f"/account/tokens/{token.pk}/revoke").status_code == 303
    assert tokens.find_live(raw) is None and "No tokens yet" in c.get("/account").text
    other = get_user_model().objects.create_user("other", password=GOOD)
    t2, _ = tokens.mint(other, "theirs")
    assert c.post(f"/account/tokens/{t2.pk}/revoke").status_code == 404        # not yours
    assert tokens.find_live is not None and t2.is_live


def test_a_flagged_user_cannot_mint(site):
    accounts.set_must_change(site, True)
    c = WebClient()
    c.django.force_login(site)
    r = c.post("/account/tokens", data={"name": "x"})
    assert r.status_code == 403 and "Change the default password first" in r.text and not ApiToken.objects.exists()


def test_command_prints_the_token_once(site, capsys):
    call_command("api_token", "sam", "--name", "agent")
    out, err = capsys.readouterr()
    assert out.strip().startswith("mnt_") and "'agent'" in err and tokens.find_live(out.strip()) is not None
    with pytest.raises(Exception, match="no user"):
        call_command("api_token", "nobody", "--name", "x")


def test_a_bearer_value_is_masked_in_logs(site):
    from app.logging_setup import redact
    _, raw = tokens.mint(site, "x")
    assert raw not in redact(f"request Authorization: Bearer {raw} from 127.0.0.1")
