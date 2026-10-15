"""SimpleFIN client (app/simplefin/client.py) through httpx's mock transport: the URL
loses its userinfo and gains Basic auth, the window and filters become query params,
402/403 raise typed errors, other failures carry the status only."""

import base64
import json

import httpx
import pytest

from app.simplefin import client as sf

ACCESS = "https://u:p%40ss@bridge.test/simplefin"


def _transport(handler):
    return httpx.MockTransport(handler)


def test_split_access_url_refuses_http_and_missing_credential():
    base, auth = sf.split_access_url(ACCESS)
    assert base == "https://bridge.test/simplefin" and isinstance(auth, httpx.BasicAuth)
    with pytest.raises(ValueError):
        sf.split_access_url("http://u:p@bridge.test/simplefin")
    with pytest.raises(ValueError):
        sf.split_access_url("https://bridge.test/simplefin")


def test_fetch_sends_basic_auth_and_no_userinfo_in_url():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["params"] = request.url.params.multi_items()
        return httpx.Response(200, json={"connections": [], "accounts": [{"id": "a1", "balance": "1"}]})

    c = sf.SimpleFinClient(ACCESS, transport=_transport(handler))
    s = c.fetch_accounts(1700000000, 1700086400, pending=True, balances_only=True, account_ids=["a1", "a2"])
    assert "@" not in seen["url"] and seen["url"].startswith("https://bridge.test/simplefin/accounts?")
    assert seen["auth"] == "Basic " + base64.b64encode(b"u:p@ss").decode()   # decoded userinfo
    assert seen["params"] == [("version", "2"), ("start-date", "1700000000"), ("end-date", "1700086400"),
                              ("pending", "1"), ("balances-only", "1"), ("account", "a1"), ("account", "a2")]
    assert s.accounts[0].id == "a1" and c.requests_made == 1
    assert repr(c) == "SimpleFinClient(bridge.test)" and "p@ss" not in repr(c)


def test_dates_become_utc_epochs():
    from datetime import date, datetime, timezone
    assert sf.to_epoch(date(2026, 1, 1)) == 1767225600
    assert sf.to_epoch(datetime(2026, 1, 1, tzinfo=timezone.utc)) == 1767225600
    assert sf.to_epoch(datetime(2026, 1, 1)) == 1767225600          # naive = UTC


@pytest.mark.parametrize("status,exc", [(403, sf.SimpleFinAuthError), (402, sf.SimpleFinPaymentError),
                                        (500, sf.SimpleFinError), (404, sf.SimpleFinError)])
def test_error_statuses_raise_typed_errors_without_the_body(status, exc):
    c = sf.SimpleFinClient(ACCESS, transport=_transport(
        lambda r: httpx.Response(status, text="secret body https://x:y@leak/ do not log")))
    with pytest.raises(exc) as ei:
        c.fetch_accounts()
    assert ei.value.status == status and "leak" not in str(ei.value)
    assert c.requests_made == 1                                      # a failed call still counts


def test_transport_error_and_bad_json():
    def boom(r):
        raise httpx.ConnectError("no route")
    with pytest.raises(sf.SimpleFinError) as ei:
        sf.SimpleFinClient(ACCESS, transport=_transport(boom)).fetch_accounts()
    assert ei.value.status is None
    with pytest.raises(sf.SimpleFinError):
        sf.SimpleFinClient(ACCESS, transport=_transport(lambda r: httpx.Response(200, text="<html>"))).fetch_accounts()


def test_from_env(monkeypatch):
    monkeypatch.delenv(sf.ENV_VAR, raising=False)
    assert sf.SimpleFinClient.from_env() is None
    monkeypatch.setenv(sf.ENV_VAR, ACCESS)
    assert sf.SimpleFinClient.from_env().base_url == "https://bridge.test/simplefin"
