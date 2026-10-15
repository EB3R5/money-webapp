"""Credential redaction (app/logging_setup.py): userinfo in any URL, the configured
Access URL's credential literal, and Authorization values never reach a handler."""

import logging

import httpx

from app import logging_setup as ls
from app.simplefin import client as sf


def test_redact_masks_userinfo_auth_headers_and_literals():
    assert ls.redact("GET https://user:s3cret@bridge.simplefin.org/simplefin/accounts") == \
        "GET https://***@bridge.simplefin.org/simplefin/accounts"
    assert ls.redact("https://u@h/") == "https://***@h/"
    assert ls.redact("Authorization: Basic dXNlcjpwYXNz next") == "Authorization: Basic *** next"
    assert ls.redact("headers={'authorization': 'Bearer abc.def'}") == "headers={'authorization': 'Bearer ***'}"
    assert ls.redact("token u:s3cret here", literals=["u:s3cret"]) == "token *** here"
    assert ls.redact("plain text") == "plain text"


def test_userinfo_of():
    assert ls.userinfo_of("https://user:pass@host/x") == "user:pass"
    assert ls.userinfo_of("https://host/x") is None


def test_filter_rewrites_records_and_args(caplog):
    flt = ls.RedactingFilter(lambda: ["demo:demo"])
    lg = logging.getLogger("test.redaction")
    lg.addFilter(flt)
    try:
        with caplog.at_level(logging.INFO, logger="test.redaction"):
            lg.info("fetch %s with %s", "https://demo:demo@beta-bridge.simplefin.org/simplefin",
                    {"Authorization": "Basic ZGVtbzpkZW1v"})
            lg.info("literal demo:demo leaked; other https://a:b@c/")
    finally:
        lg.removeFilter(flt)
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs[0] == "fetch https://***@beta-bridge.simplefin.org/simplefin with {'Authorization': 'Basic ZGVtbzpkZW1v'}"
    assert msgs[1] == "literal *** leaked; other https://***@c/"
    assert not any("demo:demo" in m for m in msgs)


def test_configure_logging_reads_the_configured_access_url(monkeypatch, caplog):
    from app import config
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", "https://me:hunter2@bridge.test/simplefin")
    flt = ls.configure_logging()
    assert flt in logging.getLogger().filters and flt in logging.getLogger("httpx").filters
    assert logging.getLogger("httpx").level == logging.WARNING
    with caplog.at_level(logging.WARNING, logger="money"):
        logging.getLogger("money").warning("cred me:hunter2 in the clear")
    assert caplog.records[-1].getMessage() == "cred *** in the clear"
    assert ls.configure_logging() is flt                             # idempotent


def test_client_never_puts_the_credential_in_the_url_or_repr():
    seen = {}
    c = sf.SimpleFinClient("https://me:hunter2@bridge.test/simplefin", transport=httpx.MockTransport(
        lambda r: (seen.update(url=str(r.url), auth=r.headers["authorization"]) or httpx.Response(200, json={}))))
    c.fetch_accounts()
    assert "hunter2" not in seen["url"] and seen["auth"].startswith("Basic ")
    assert "hunter2" not in repr(c)


def test_django_and_gunicorn_loggers_are_covered():
    from app.logging_setup import LOGGER_NAMES
    for name in ("django", "django.request", "django.security", "gunicorn.error", "gunicorn.access"):
        assert name in LOGGER_NAMES


def test_redact_masks_invitation_and_reset_link_paths():
    """An unspent link's token is a path segment; the access log must not print it."""
    tok = "k3Q9x_wLm7-ZpA1bC2dE3fG4hI5jK6lM7nO8pQ9rS0t"
    assert ls.redact(f'"GET /register/{tok} HTTP/1.1" 200') == '"GET /register/*** HTTP/1.1" 200'
    assert ls.redact(f"POST /reset/{tok}") == "POST /reset/***"
    assert ls.redact("GET /register/short") == "GET /register/short"       # not a token
    assert ls.redact("GET /settings/users/reset") == "GET /settings/users/reset"
