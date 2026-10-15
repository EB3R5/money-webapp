"""The unlinked feed accounts strip on the Accounts page and its routes
(app/views/accounts.py over app/simplefin/link.py)."""

from app.simplefin import link
from app.store.accounts import accounts
from app.store.credit_accounts import credit_accounts
from tests import dbhelper
from tests.test_feed_link import _first_run


def test_strip_absent_without_placeholders(store_client):
    dbhelper.seed_accounts()
    html = (store_client.get("/accounts")).text
    assert 'id="feed-strip"' not in html and 'id="feed-ignored"' not in html
    d = (store_client.get("/api/accounts/unlinked")).json()
    assert d["unlinked"] == [] and d["ignored"] == [] and "Bank/cash" in d["kinds"]
    assert "Common stock" not in d["kinds"]                          # a bank feed never carries a stock


def test_strip_lists_placeholders_with_link_and_promote_choices(store_client):
    dbhelper.seed_accounts()
    ph = _first_run()
    html = (store_client.get("/accounts")).text
    assert 'id="feed-strip"' in html and f'data-feed-id="{ph["_id"]}"' in html
    assert "Demo Bank" in html and "$1,235" in html                   # name, institution, balance
    assert '<option value="acc1">Checking (Assets)</option>' in html  # linkable card
    assert 'value="acc3"' not in html                                 # closed cards are not offered
    assert '<option value="Bank/cash">' in html and '<option value="Credit card">' in html
    assert 'id="feed-ignored"' not in html
    d = (store_client.get("/api/accounts/unlinked")).json()
    assert [u["_id"] for u in d["unlinked"]] == [ph["_id"]] and [c["_id"] for c in d["cards"]] == ["acc1", "acc2"]


def test_link_route_then_strip_goes_away(store_client):
    dbhelper.seed_accounts()
    ph = _first_run()
    r = store_client.post("/api/accounts/link", json={"feed_id": ph["_id"], "card_id": "acc1"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["transactions"] == 2
    assert (accounts.get("acc1"))["simplefin_account_id"] == "acc-1"
    html = (store_client.get("/accounts")).text
    assert 'id="feed-strip"' not in html and 'data-id="acc1"' in html
    r = store_client.post("/api/accounts/link", json={"feed_id": ph["_id"], "card_id": "acc1"})
    assert r.status_code == 404                                         # gone


def test_promote_route_credit_card_gets_its_registry_entry(store_client):
    ph = _first_run()
    r = store_client.post("/api/accounts/promote", json={"feed_id": ph["_id"], "kind": "Common stock"})
    assert r.status_code == 400 and "kind must be" in r.json()["error"]
    r = store_client.post("/api/accounts/promote", json={"feed_id": ph["_id"], "kind": "Credit card"})
    assert r.status_code == 200 and r.json()["credit_entry"] is True
    card = accounts.get(ph["_id"])
    assert card["Type"] == "Liabilities" and card["Account Kind"] == "Credit card" and not card["is_hidden"]
    entry = credit_accounts.one({"account_id": card["Account ID"]})
    assert entry["name"] == "Checking" and entry["balance_account"] == "Checking" and entry["status"] == "Active"
    html = (store_client.get("/accounts")).text
    assert 'id="feed-strip"' not in html and "Liabilities" in html


def test_ignore_and_unignore_routes_drive_the_fold_out(store_client):
    ph = _first_run()
    r = store_client.post("/api/accounts/ignore", json={"feed_id": ph["_id"]})
    assert r.json() == {"ok": True, "transactions": 2, "snapshots": 1}
    html = (store_client.get("/accounts")).text
    assert 'id="feed-strip"' not in html and 'id="feed-ignored"' in html and "Ignored feed accounts (1)" in html
    r = store_client.post("/api/accounts/unignore", json={"feed_id": ph["_id"]})
    assert r.json() == {"ok": True}
    html = (store_client.get("/accounts")).text
    assert 'id="feed-strip"' in html and 'id="feed-ignored"' not in html
    assert link.is_placeholder(accounts.get(ph["_id"]))
    r = store_client.post("/api/accounts/ignore", json={"feed_id": "nope"})
    assert r.status_code == 404
