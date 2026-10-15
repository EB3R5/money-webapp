"""Auth gate + hardened login flow on django.contrib.auth (app/views/auth.py): rate limit
(429 + Retry-After), unknown username and wrong password answered alike, session cycled on
login and cleared on logout, no bearer bypass."""

import pytest
from django.contrib.auth import get_user_model

from app.security import LoginRateLimiter, limiter
from app.views.auth import client_ip
from django.test import RequestFactory
from tests import dbhelper
from tests.client import WebClient

PASSWORD = "s3cret-pw-long-enough"


@pytest.fixture
def auth_client(store_db, settings):
    dbhelper.seed_ledger()
    get_user_model().objects.create_user("me", password=PASSWORD)
    limiter._user.clear(); limiter._ip.clear()      # in-process state, fresh per test
    settings.MONEY_AUTH_GATE = True                 # exercise the real gate
    return WebClient()                              # CSRF off: the form's token is tests/test_security.py's job


def _login(c, username="me", password=PASSWORD, **extra):
    return c.post("/login", data={"username": username, "password": password, **extra})


# --- gate ----------------------------------------------------------------------------

def test_unauth_page_redirects_to_login(auth_client):
    r = auth_client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_unauth_api_returns_401(auth_client):
    assert auth_client.get("/api/transactions/doc/t1").status_code == 401


def test_login_page_and_healthz_are_exempt(auth_client):
    assert auth_client.get("/login").status_code == 200
    r = auth_client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_bearer_token_does_not_bypass_the_gate(auth_client):
    r = auth_client.get("/api/transactions/doc/t1", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 401


# --- login ---------------------------------------------------------------------------

def test_bad_password_and_unknown_username_rejected_generically(auth_client):
    r = _login(auth_client, password="wrong")
    assert r.status_code == 401 and "Invalid credentials." in r.text
    r = _login(auth_client, username="nobody")
    assert r.status_code == 401 and "Invalid credentials." in r.text
    # the failure was counted against (address, "nobody") like any other bad login
    assert [len(v) for k, v in limiter._user.items() if k[1] == "nobody"] == [1]


def test_sixth_bad_login_is_429_with_retry_after(auth_client):
    for _ in range(5):
        assert _login(auth_client, password="wrong").status_code == 401
    r = _login(auth_client)                                # even a correct one is refused now
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert "Too many attempts" in r.text
    # the same address may still try another username (per-IP cap is 20)
    assert _login(auth_client, username="other").status_code == 401
    # the wrong-password attempts are case-insensitive on the username
    assert _login(auth_client, username="ME").status_code == 429


def test_limiter_windows_and_per_ip_cap():
    lim = LoginRateLimiter(per_user=2, per_ip=3, window_s=100)
    t = 1000.0
    lim.record_failure("1.1.1.1", "Me", t); lim.record_failure("1.1.1.1", "me ", t + 1)
    assert lim.retry_after("1.1.1.1", "ME", t + 2) == 99                # window ends at t+100
    assert lim.retry_after("1.1.1.1", "you", t + 2) == 0
    lim.record_failure("1.1.1.1", "you", t + 2)
    assert lim.retry_after("1.1.1.1", "anyone", t + 3) == 98            # per-IP cap of 3 hit
    assert lim.retry_after("2.2.2.2", "me", t + 3) == 0                  # another address is fine
    assert lim.retry_after("1.1.1.1", "me", t + 101) == 0                # window slid
    lim.record_failure("3.3.3.3", "me", t); lim.record_failure("3.3.3.3", "me", t)
    lim.record_success("3.3.3.3", "me")
    assert lim.retry_after("3.3.3.3", "me", t + 1) == 0                  # success clears the user bucket


def test_client_ip_walks_the_forwarded_header_from_the_right_past_trusted_proxies(settings):
    rf = RequestFactory()
    # one proxy on loopback: the hop it wrote (the rightmost) is the client
    assert client_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="100.64.0.9")) == "100.64.0.9"
    # a client-supplied value ahead of it is never believed: the lockout cannot be dodged
    assert client_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="1.2.3.4, 100.64.0.9")) == "100.64.0.9"
    # an untrusted peer: the header is ignored
    assert client_ip(rf.get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="100.64.0.9")) == "10.0.0.5"
    assert client_ip(rf.get("/", REMOTE_ADDR="10.0.0.5")) == "10.0.0.5"
    settings.TRUSTED_PROXIES = ["172.21.0.0/16", "10.0.0.5"]            # a proxy container, a proxy host
    assert client_ip(rf.get("/", REMOTE_ADDR="172.21.0.3", HTTP_X_FORWARDED_FOR="203.0.113.7")) == "203.0.113.7"
    # two trusted proxies in a row: walk past both
    assert client_ip(rf.get("/", REMOTE_ADDR="172.21.0.3", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.5")) == "203.0.113.7"
    assert client_ip(rf.get("/", REMOTE_ADDR="192.168.1.9", HTTP_X_FORWARDED_FOR="203.0.113.7")) == "192.168.1.9"
    # garbage in the hop falls back to the connection
    assert client_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="unknown")) == "127.0.0.1"
    assert client_ip(rf.get("/", REMOTE_ADDR="", HTTP_X_FORWARDED_FOR="203.0.113.7")) == ""


def test_login_cycles_the_session_and_logout_clears_it(auth_client):
    before = auth_client.get("/login").cookies.get("money_session")   # a pre-login session may exist
    r = _login(auth_client)
    assert r.status_code == 303 and r.headers["location"] == "/"
    after = r.cookies.get("money_session")
    assert after and after != before
    assert auth_client.get("/").status_code == 200            # through the gate
    assert auth_client.get("/login").status_code == 303       # signed in: no form
    r = auth_client.post("/logout")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert auth_client.get("/").status_code == 303


def test_login_follows_a_local_next(auth_client):
    r = _login(auth_client, next="/categories")
    assert r.status_code == 303 and r.headers["location"] == "/categories"


def test_session_default_is_24h_and_docs_dropped_the_token():
    from pathlib import Path
    src = Path("app/config.py").read_text()
    assert 'SESSION_MAX_AGE", "86400"' in src
    for f in (".env.example", "docs/deployment.md"):
        text = Path(f).read_text()
        assert "API_TOKEN" not in text
    assert 'SESSION_MAX_AGE="86400"' in Path(".env.example").read_text()
    assert "default 24 hours" in Path("docs/deployment.md").read_text()


def test_remember_me_keeps_the_session_thirty_days(auth_client, settings):
    from django.contrib.sessions.models import Session
    from django.utils import timezone
    r = _login(auth_client)
    assert r.status_code == 303
    row = Session.objects.get(session_key=r.cookies["money_session"])
    assert 0 < (row.expire_date - timezone.now()).total_seconds() <= settings.SESSION_COOKIE_AGE + 5
    auth_client.post("/logout")
    r = _login(auth_client, remember="1")
    assert r.status_code == 303
    key = r.cookies["money_session"]
    row = Session.objects.get(session_key=key)
    assert 29 <= (row.expire_date - timezone.now()).days <= 30
    assert "max-age=2592000" in auth_client.django.cookies["money_session"].output().lower()
    assert auth_client.get("/").status_code == 200
    Session.objects.filter(session_key=key).delete()           # revocation still works
    assert auth_client.get("/").status_code == 303


def test_remember_me_does_not_change_the_forced_change_or_the_limiter(auth_client, settings):
    from app import accounts
    user = get_user_model().objects.get(username="me")
    accounts.set_must_change(user, True)
    r = _login(auth_client, remember="1")
    assert r.status_code == 303 and r.headers["location"] == "/account?forced=1"
    auth_client.post("/logout")
    for _ in range(5):
        _login(auth_client, password="wrong", remember="1")
    assert _login(auth_client, remember="1").status_code == 429
