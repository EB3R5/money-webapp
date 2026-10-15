"""Mealie-style accounts (app/accounts.py, ADR-0024): with no account the first visit to
/login is the setup form; a headless deployment sets DEFAULT_USER / DEFAULT_PASSWORD and the
first start seeds that admin, flagged to change the password; a flagged user may open
/account only until it is changed; more users come from /admin/, whose own login form is
never shown. A bcrypt hash (the FastAPI build's, imported at the cutover) still verifies."""

import re

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from app import accounts
from app.models import Profile
from tests import dbhelper
from tests.client import WebClient

GOOD = "a-long-enough-password-1"


@pytest.fixture
def gated(store_db, settings):
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "changeme", "changeme"   # the headless path
    return WebClient()


def _token_from(html: str) -> str:
    return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)


# --- bootstrap ---------------------------------------------------------------------------

def test_bootstrap_creates_the_default_admin_once(store_db, settings, caplog):
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "changeme", "changeme"
    assert accounts.ensure_admin().startswith("created the default admin 'changeme'")
    user = get_user_model().objects.get(username="changeme")
    assert user.is_superuser and user.is_staff and user.check_password("changeme")
    assert accounts.must_change_password(user) is True
    assert any("default password" in r.getMessage() for r in caplog.records)
    assert accounts.ensure_admin() == "users exist; nothing to do"            # idempotent
    assert get_user_model().objects.count() == 1


def test_bootstrap_honours_default_user_and_password(store_db, settings):
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "chris", "a-chosen-first-password"
    accounts.ensure_admin()
    user = get_user_model().objects.get(username="chris")
    assert user.check_password("a-chosen-first-password") and accounts.must_change_password(user)



def test_bootstrap_without_defaults_creates_nothing(store_db, settings, capsys):
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "", ""
    call_command("bootstrap_admin")
    assert "setup form" in capsys.readouterr().out
    assert not get_user_model().objects.exists()
    settings.DEFAULT_USER = "onlyhalf"                       # one of the two is not enough
    assert "setup form" in accounts.ensure_admin()


def test_commands_wrap_the_same_logic(store_db, settings, capsys):
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "changeme", "changeme"
    call_command("bootstrap_admin")
    assert "created the default admin" in capsys.readouterr().out
    call_command("bootstrap_admin")
    assert "nothing to do" in capsys.readouterr().out



# --- the legacy password logs in and is upgraded --------------------------------------------


# --- forced change -----------------------------------------------------------------------

def test_default_password_forces_a_change_before_anything_else(gated):
    accounts.ensure_admin()
    r = gated.post("/login", data={"username": "changeme", "password": "changeme"})
    assert r.status_code == 303 and r.headers["location"] == "/account?forced=1"
    r = gated.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/account?forced=1"
    r = gated.get("/api/transactions/doc/t1")
    assert r.status_code == 403 and r.json() == {"detail": "Password change required"}
    page = gated.get("/account")
    assert page.status_code == 200 and "still has its default password" in page.text
    # the default (common, short) is refused as a new password; a good one is accepted
    r = gated.post("/account", data={"old_password": "changeme", "new_password1": "changeme", "new_password2": "changeme"})
    assert r.status_code == 400 and "too short" in r.text
    r = gated.post("/account", data={"old_password": "wrong", "new_password1": GOOD, "new_password2": GOOD})
    assert r.status_code == 400 and "incorrect" in r.text
    r = gated.post("/account", data={"old_password": "changeme", "new_password1": GOOD, "new_password2": GOOD})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert gated.get("/").status_code == 200                       # still signed in, flag cleared
    assert not Profile.objects.get(user__username="changeme").must_change_password
    assert get_user_model().objects.get(username="changeme").check_password(GOOD)


def test_account_page_for_an_unflagged_user_and_logout_still_works_while_flagged(gated):
    accounts.ensure_admin()
    gated.post("/login", data={"username": "changeme", "password": "changeme"})
    assert gated.post("/logout").status_code == 303                 # /logout is exempt
    user = get_user_model().objects.create_user("other", password=GOOD)
    gated.django.force_login(user)
    page = gated.get("/account")
    assert page.status_code == 200 and "still has its default password" not in page.text


# --- admin ------------------------------------------------------------------------------------

def test_admin_login_form_is_the_apps_and_a_user_added_there_can_sign_in(gated, settings):
    accounts.ensure_admin()
    r = gated.get("/admin/login/")
    assert r.status_code == 302 and r.headers["location"] == "/login?next=/admin/"
    r = gated.get("/admin/")
    assert r.status_code == 302 and "/admin/login/" in r.headers["location"]      # the admin's own staff check
    admin = get_user_model().objects.get(username="changeme")
    admin.set_password(GOOD); admin.save(); accounts.set_must_change(admin, False)
    r = gated.post("/login", data={"username": "changeme", "password": GOOD, "next": "/admin/"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/"
    index = gated.get("/admin/")
    assert index.status_code == 200 and "Users" in index.text
    # the admin's pages run under the strict CSP: no inline script without a nonce, no handlers
    for path in ("/admin/", "/admin/auth/user/", "/admin/auth/user/add/"):
        html = gated.get(path).text
        for m in re.finditer(r"<script\b([^>]*)>", html):
            attrs = m.group(1)
            assert "src=" in attrs or 'type="application/json"' in attrs or "nonce=" in attrs, (path, attrs)
        assert not re.search(r"\son[a-z]+=", html), path
    token = _token_from(gated.get("/admin/auth/user/add/").text)
    r = gated.post("/admin/auth/user/add/", data={"csrfmiddlewaretoken": token, "username": "friend",
                                                   "password1": GOOD, "password2": GOOD})
    assert r.status_code == 302
    gated.post("/logout")
    r = gated.post("/login", data={"username": "friend", "password": GOOD})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert gated.get("/").status_code == 200
    assert gated.get("/admin/").status_code == 302              # not staff: no admin


def test_next_must_be_local(gated):
    accounts.ensure_admin()
    admin = get_user_model().objects.get(username="changeme")
    admin.set_password(GOOD); admin.save(); accounts.set_must_change(admin, False)
    r = gated.post("/login", data={"username": "changeme", "password": GOOD, "next": "https://evil.example/"})
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_forced_change_with_csrf_enforced(store_db, settings):
    """The real browser flow: the token from the account page passes the CSRF check after
    the login rotated it."""
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "changeme", "changeme"
    accounts.ensure_admin()
    c = WebClient(enforce_csrf_checks=True)
    token = _token_from(c.get("/login").text)
    r = c.post("/login", data={"csrfmiddlewaretoken": token, "username": "changeme", "password": "changeme"})
    assert r.status_code == 303
    page = c.get("/account")
    assert page.status_code == 200
    token2 = _token_from(page.text)
    r = c.post("/account", data={"csrfmiddlewaretoken": token2, "old_password": "changeme",
                                 "new_password1": GOOD, "new_password2": GOOD})
    assert r.status_code == 303, r.text[:300]
    assert c.get("/").status_code == 200


def test_flagged_user_cannot_use_the_admin_either(gated):
    accounts.ensure_admin()
    gated.post("/login", data={"username": "changeme", "password": "changeme"})
    r = gated.get("/admin/")
    assert r.status_code == 303 and r.headers["location"] == "/account?forced=1"


def test_a_bcrypt_hash_from_the_old_build_still_logs_in_and_is_upgraded(gated):
    import bcrypt
    user = get_user_model().objects.create_user("me")
    user.password = "bcrypt$" + bcrypt.hashpw(b"the-old-password", bcrypt.gensalt()).decode("ascii")
    user.save()
    r = gated.post("/login", data={"username": "me", "password": "the-old-password"})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert get_user_model().objects.get(username="me").password.startswith("pbkdf2_sha256$")


# --- the setup form -------------------------------------------------------------------------

@pytest.fixture
def fresh(store_db, settings):
    """A fresh install with no defaults in the environment: the setup form is the way in."""
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "", ""
    from app.security import limiter
    limiter._user.clear(); limiter._ip.clear()
    return WebClient()


def test_fresh_install_login_is_the_setup_form_until_an_account_exists(fresh):
    r = fresh.get("/login")
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    page = fresh.get("/setup")
    assert page.status_code == 200 and "No account exists yet" in page.text and 'action="/setup"' in page.text
    assert fresh.get("/").status_code == 303                       # the gate still holds
    r = fresh.post("/setup", data={"username": "chris", "password1": GOOD, "password2": GOOD})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert fresh.get("/").status_code == 200                       # signed in, straight to the Ledger
    user = get_user_model().objects.get(username="chris")
    assert user.is_superuser and user.is_staff and not accounts.must_change_password(user)
    # closed for good
    assert fresh.get("/setup").status_code == 303 and fresh.get("/setup").headers["location"] == "/login"
    fresh.post("/logout")
    assert fresh.get("/login").status_code == 200 and "No account exists yet" not in fresh.get("/login").text
    r = fresh.post("/setup", data={"username": "other", "password1": GOOD, "password2": GOOD})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert get_user_model().objects.count() == 1


def test_setup_form_validates_and_counts_failures(fresh):
    r = fresh.post("/setup", data={"username": "chris", "password1": "short", "password2": "short"})
    assert r.status_code == 400 and "too short" in r.text and 'value="chris"' in r.text
    r = fresh.post("/setup", data={"username": "chris", "password1": GOOD, "password2": GOOD + "x"})
    assert r.status_code == 400 and "do not match" in r.text
    r = fresh.post("/setup", data={"username": "", "password1": GOOD, "password2": GOOD})
    assert r.status_code == 400 and "username is required" in r.text
    r = fresh.post("/setup", data={"username": "christopher-johnson", "password1": "christopher-johnson1",
                                   "password2": "christopher-johnson1"})
    assert r.status_code == 400 and "too similar" in r.text
    assert not get_user_model().objects.exists()
    for _ in range(2):
        fresh.post("/setup", data={"username": "chris", "password1": "short", "password2": "short"})
    r = fresh.post("/setup", data={"username": "chris", "password1": GOOD, "password2": GOOD})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0 and "Too many attempts" in r.text


def test_setup_form_over_https_with_csrf_enforced(store_db, settings):
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "", ""
    from app.security import limiter
    limiter._user.clear(); limiter._ip.clear()                     # process state, filled by the test above
    c = WebClient(enforce_csrf_checks=True)
    token = _token_from(c.get("/setup", secure=True).text)
    r = c.post("/setup", data={"username": "chris", "password1": GOOD, "password2": GOOD}, secure=True,
               headers={"Origin": "https://testserver"})
    assert r.status_code == 403                                     # no token: refused before anything
    r = c.post("/setup", data={"csrfmiddlewaretoken": token, "username": "chris", "password1": GOOD, "password2": GOOD},
               secure=True, headers={"Origin": "https://testserver"})
    assert r.status_code == 303 and c.get("/", secure=True).status_code == 200


def test_a_second_setup_in_flight_loses(store_db, settings):
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "", ""
    accounts.create_first_admin("first", GOOD, must_change=False)
    with pytest.raises(accounts.AlreadySetUp):
        accounts.create_first_admin("second", GOOD, must_change=False)
    assert get_user_model().objects.count() == 1


def test_headless_defaults_skip_the_setup_form(store_db, settings):
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    settings.DEFAULT_USER, settings.DEFAULT_PASSWORD = "ops", "a-long-first-password"
    accounts.ensure_admin()
    c = WebClient()
    assert c.get("/login").status_code == 200 and c.get("/setup").status_code == 303
