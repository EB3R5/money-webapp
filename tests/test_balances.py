"""Balances on the store layer: the Grid over balance_history (block paging, the granular
"Account Type" column, search, inline update, delete with audit) and the from-account
Snapshot stamp that reads the accounts store and inherits Institution/Class by Account ID."""

import pytest

from app.store.accounts import accounts
from app.store.balance_history import balance_history
from app.store.deletions import deletions
from tests import dbhelper


@pytest.fixture
def bal_client(store_db, settings):
    from tests.client import WebClient
    dbhelper.seed_balances()
    settings.MONEY_AUTH_GATE = False
    return WebClient()


def test_page_renders_total_without_a_sync_button(bal_client):
    r = bal_client.get("/balances")
    assert r.status_code == 200 and "2 balance snapshots" in r.text
    assert "sync-btn" not in r.text          # the Sheets path is gone (ADR-0015)


def test_block_serves_account_type_column_sorted_by_date(bal_client):
    r = bal_client.post("/api/balances", json={"startRow": 0, "endRow": 100})
    body = r.json()
    assert body["lastRow"] == 2
    assert [x["_id"] for x in body["rows"]] == ["b2", "b1"]     # default sort: Date desc
    row = next(x for x in body["rows"] if x["_id"] == "b1")
    assert row["Account Type"] == "Checking" and row["Date"] == "2024-01-02"
    assert "Type" not in row                                       # the coarse kind stays off the grid


def test_update_writes_account_type_and_coerces_balance(bal_client):
    r = bal_client.post("/api/balances/update",
                              json={"id": "b1", "field": "Account Type", "value": "Savings"})
    assert r.json() == {"ok": True}
    r = bal_client.post("/api/balances/update",
                              json={"id": "b1", "field": "Balance", "value": "$1,234.50"})
    assert r.json() == {"ok": True}
    doc = balance_history.get("b1")
    assert doc["Account Type"] == "Savings" and doc["Balance"] == 1234.5
    r = bal_client.post("/api/balances/update",
                              json={"id": "b1", "field": "Balance", "value": "abc"})
    assert r.status_code == 400


def test_search_matches_account_institution_class(bal_client):
    r = bal_client.post("/api/balances", json={"startRow": 0, "endRow": 100, "q": "ally"})
    assert r.json()["lastRow"] == 1
    r = bal_client.post("/api/balances", json={"startRow": 0, "endRow": 100, "q": "liab"})
    assert [x["_id"] for x in r.json()["rows"]] == ["b2"]


def test_add_row_defaults_date_and_delete_audits(bal_client):
    r = bal_client.post("/api/balances/row",
                              json={"Account": "Brokerage", "Account Type": "Common Stock", "Balance": "10"})
    body = r.json()
    assert body["ok"] and body["row"]["Account Type"] == "Common Stock"
    assert (balance_history.get(body["id"]))["Date"] is not None
    r = bal_client.post("/api/balances/delete", json={"ids": [body["id"], "b2"]})
    assert r.json() == {"ok": True, "deleted": 2}
    assert balance_history.count() == 1
    logged = deletions.list({"collection": "balance_history"})
    assert sorted(d["doc"]["_id"] for d in logged) == sorted([body["id"], "b2"])


def test_from_account_inherits_by_account_id_and_falls_back_to_coarse_type(bal_client):
    r = bal_client.post("/api/balances/from-account/acc1")
    body = r.json()
    assert body["ok"]
    snap = balance_history.get(body["id"])
    assert snap["Balance"] == 1000.0 and snap["Account"] == "Checking"
    assert snap["Account ID"] == "A1" and snap["_src"] == "manual"
    assert snap["Institution"] == "Ally" and snap["Class"] == "Asset"   # inherited from b1
    assert snap["Account Type"] == "Assets"    # legacy card: coarse Type stands in
    assert snap["Type"] == "Assets" and "Account #" not in {k for k, v in snap.items() if v}
    assert body["row"]["Account Type"] == "Assets"


def test_from_account_prefers_granular_account_type(bal_client):
    dbhelper.seed(accounts, [{"_id": "acc9", "Account ID": "A9", "Account": "Granular",
                                    "Type": "Assets", "Account Type": "Checking Account",
                                    "Amount": 50.0, "Status": "Active"}])
    r = bal_client.post("/api/balances/from-account/acc9")
    snap = balance_history.get(r.json()["id"])
    assert snap["Account Type"] == "Checking Account" and snap["Type"] == "Assets"
    assert snap.get("Institution") is None       # no prior Snapshot to inherit from


def test_from_account_unknown_is_404(bal_client):
    r = bal_client.post("/api/balances/from-account/nope")
    assert r.status_code == 404
