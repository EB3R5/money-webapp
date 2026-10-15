"""The Ledger section on the store layer: the Grid datasource (block paging, sort, LIKE
search, coerce, add row, inline update, delete-with-audit, drill-down) plus the ledger
Category cascade and the page render. Seeded through tests/dbhelper.py."""

from app.grid import Grid
from app.views import ledger as led
from app.store.deletions import deletions
from app.store.transactions import transactions
from tests import dbhelper


def test_ledger_grid_is_store_backed():
    assert isinstance(led.grid, Grid) and led.grid.store is transactions


def test_block_pages_sorts_and_searches(store_client):
    r = store_client.post("/api/transactions", json={
        "startRow": 0, "endRow": 2, "sortModel": [{"colId": "Date", "sort": "asc"}]})
    d = r.json()
    assert d["lastRow"] == 3                      # 3 seeded transactions
    assert len(d["rows"]) == 2                    # block limit honored
    assert d["rows"][0]["Date"] == "2024-05-01" and d["rows"][1]["Date"] == "2024-05-02"
    # default sort is Date desc
    d2 = (store_client.post("/api/transactions", json={"startRow": 0, "endRow": 100})).json()
    assert [x["_id"] for x in d2["rows"]] == ["t3", "t2", "t1"]
    # case-insensitive substring search across Description/Category/Account
    d3 = (store_client.post("/api/transactions",
                                  json={"startRow": 0, "endRow": 100, "q": "coffee"})).json()
    assert d3["lastRow"] == 1 and d3["rows"][0]["Description"] == "Coffee"
    d4 = (store_client.post("/api/transactions",
                                  json={"startRow": 0, "endRow": 100, "q": "checking"})).json()
    assert d4["lastRow"] == 2                     # Account matches


def test_block_offset_pages_past_the_first_block(store_client):
    d = (store_client.post("/api/transactions", json={"startRow": 2, "endRow": 4})).json()
    assert [x["_id"] for x in d["rows"]] == ["t1"] and d["lastRow"] == 3


def test_inline_update_coerces_amount_and_stamps_edit(store_client):
    r = store_client.post("/api/transactions/update",
                                json={"id": "t1", "field": "Amount", "value": "-$9.99"})
    assert r.json() == {"ok": True}
    doc = dbhelper.get(transactions, "t1")
    assert doc["Amount"] == -9.99 and doc["_edited_at"] is not None


def test_inline_update_rejects_bad_number_and_unknown_id(store_client):
    r = store_client.post("/api/transactions/update",
                                json={"id": "t1", "field": "Amount", "value": "abc"})
    assert r.status_code == 400
    r2 = store_client.post("/api/transactions/update",
                                 json={"id": "nope", "field": "Amount", "value": "1"})
    assert r2.json() == {"ok": False}


def test_update_rejects_non_editable_field(store_client):
    # Group is derived, not directly editable.
    r = store_client.post("/api/transactions/update",
                                json={"id": "t1", "field": "Group", "value": "X"})
    assert r.status_code == 400


def test_create_row_cascades_category_and_defaults_date(store_client):
    r = store_client.post("/api/transactions/row",
                                json={"Description": "Gas", "Amount": "40", "Category": "Auto"})
    body = r.json()
    assert body["ok"] and body["row"]["Group"] == "Transport"
    doc = dbhelper.get(transactions, body["id"])
    assert doc["Category"] == "Auto" and doc["Group"] == "Transport"   # derived (ADR-0006)
    assert doc["Amount"] == 40.0
    assert doc["Date"] is not None                # defaulted to today
    assert doc["_created_at"] is not None


def test_category_endpoint_rewrites_derived(store_client):
    r = store_client.post("/api/transactions/category", json={"id": "t2", "value": "Auto"})
    body = r.json()
    assert body["ok"] and body["derived"]["Group"] == "Transport"
    doc = dbhelper.get(transactions, "t2")
    assert doc["Category"] == "Auto" and doc["Group"] == "Transport"
    # blank commits are a no-op, missing id is a 400
    assert (store_client.post("/api/transactions/category",
                                    json={"id": "t2", "value": ""})).status_code == 400
    assert (store_client.post("/api/transactions/category",
                                    json={"value": "Auto"})).status_code == 400


def test_doc_returns_full_row_json_safe(store_client):
    transactions.update("t1", {"Full Description": "COFFEE HUT 123", "Pred:Conf": {"Food": 0.9}})
    r = store_client.get("/api/transactions/doc/t1")
    assert r.status_code == 200
    doc = r.json()["doc"]
    assert doc["_id"] == "t1" and doc["Description"] == "Coffee"
    assert doc["Full Description"] == "COFFEE HUT 123"      # fields beyond the grid columns
    assert doc["Pred:Conf"] == {"Food": 0.9}
    assert isinstance(doc["Date"], str) and isinstance(doc["_edited_at"], str)
    assert (store_client.get("/api/transactions/doc/nope")).status_code == 404


def test_delete_audits_then_removes(store_client):
    r = store_client.post("/api/transactions/delete", json={"ids": ["t3", "nope"]})
    assert r.json() == {"ok": True, "deleted": 1}
    assert dbhelper.get(transactions, "t3") is None
    audit = dbhelper.one(deletions, collection="transactions")
    assert audit is not None and audit["doc"]["_id"] == "t3" and audit["doc"]["Amount"] == -1500.0
    assert (store_client.post("/api/transactions/delete", json={"ids": []})).status_code == 400


def test_page_renders_total_categories_without_a_sync_button(store_client):
    r = store_client.get("/")
    assert r.status_code == 200
    assert "sync-btn" not in r.text          # the Sheets path is gone (ADR-0015)
    assert 'id="apply-rules-btn"' in r.text and 'id="ml-suggest-btn"' in r.text
    assert 'href="/categorization"' in r.text and 'id="suggest-rule"' in r.text
    assert "retrain-btn" not in r.text and "autocat-btn" not in r.text
    assert "3 transactions" in r.text
    assert '"Category": "Auto"' in r.text and '"Group": "Transport"' in r.text


# --- a Ledger edit on a feed row survives the next Sync run (ADR-0019) -------------------------

def test_ledger_edit_on_a_feed_row_survives_the_sync(store_client):
    import httpx
    from datetime import UTC, datetime
    from app.simplefin import sync as sf
    from app.simplefin.client import SimpleFinClient
    posted = int(datetime(2026, 9, 20, tzinfo=UTC).timestamp())
    body = {"connections": [{"conn_id": "c1", "name": "Bank"}],
            "accounts": [{"id": "acc-1", "name": "Checking", "conn_id": "c1", "balance": "1",
                          "transactions": [{"id": "t1", "posted": posted, "amount": "-4.50",
                                            "description": "COFFEE HUT", "pending": False}]}]}
    client = SimpleFinClient("https://u:p@bridge.test/simplefin",
                             transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    sf.run_sync(client=client, now=now)
    tid = sf.txn_row_id("acc-1", "t1")
    r = store_client.post("/api/transactions/update", json={"id": tid, "field": "Description", "value": "Coffee with Sam"})
    assert r.json() == {"ok": True}
    sf.run_sync(client=client, now=now)
    row = dbhelper.get(dbhelper.transactions, tid)
    assert row["Description"] == "Coffee with Sam"
    assert row["_provider"]["Description"] == "COFFEE HUT"


# --- Month follows Date on the Ledger (Grid.derive) -----------------------------------------

def test_date_edit_moves_month_and_added_rows_get_one(store_client):
    from datetime import datetime
    r = store_client.post("/api/transactions/update", json={"id": "t1", "field": "Date", "value": "2026-03-15"})
    assert r.json() == {"ok": True}
    row = dbhelper.get(dbhelper.transactions, "t1")
    assert row["Date"] == datetime(2026, 3, 15) and row["Month"] == datetime(2026, 3, 1)
    # an added row with an explicit Date
    r = store_client.post("/api/transactions/row", json={"Date": "2026-07-04", "Description": "Fireworks", "Amount": "-20"})
    assert r.json()["ok"]
    row = dbhelper.get(dbhelper.transactions, r.json()["id"])
    assert row["Month"] == datetime(2026, 7, 1)
    # and one that defaults its Date to today
    r = store_client.post("/api/transactions/row", json={"Description": "Today"})
    row = dbhelper.get(dbhelper.transactions, r.json()["id"])
    assert row["Month"] == datetime(row["Date"].year, row["Date"].month, 1)
    # an Amount edit touches nothing else
    before = (dbhelper.get(dbhelper.transactions, "t1"))["Month"]
    store_client.post("/api/transactions/update", json={"id": "t1", "field": "Amount", "value": "1"})
    assert (dbhelper.get(dbhelper.transactions, "t1"))["Month"] == before
