"""The Data page (app/views/data.py + app/store/datatable.py): every app-owned table
browsable from the live schema, hidden tables 404 everywhere, autocat editable through its
Store, everything else 403 on update."""

from datetime import datetime

from app.store.autocat import autocat
from app.store.datatable import HIDDEN, datatable
from app.store.deletions import deletions
from tests import dbhelper


def test_page_lists_browsable_tables_not_hidden_ones(store_client):
    page = (store_client.get("/data")).text
    assert 'value="transactions"' in page and 'value="deletions"' in page
    assert 'value="autocat"' in page and "autocat (0)" in page
    for hidden in HIDDEN:
        assert f'value="{hidden}"' not in page
    assert "transactions (3)" in page                       # the seeded ledger
    assert "read-only" in page                              # every table but autocat says so


def test_columns_use_store_display_keys(store_client):
    d = (store_client.get("/api/data/transactions/columns")).json()
    assert "Description" in d["columns"] and "Account #" in d["columns"]
    assert not any(c in d["columns"] for c in ("id", "created_at", "edited_at"))
    assert d["editable"] is False
    assert (store_client.get("/api/data/autocat/columns")).json()["editable"] is True


def test_rows_block_search_sort_and_doc(store_client):
    r = store_client.post("/api/data/transactions/rows", json={"startRow": 0, "endRow": 100})
    body = r.json()
    assert body["lastRow"] == 3 and {x["_id"] for x in body["rows"]} == {"t1", "t2", "t3"}
    assert body["rows"][0]["Date"] == "2024-05-01T00:00:00"      # serialized, all columns present
    r = store_client.post("/api/data/transactions/rows",
                                json={"startRow": 0, "endRow": 100, "q": "coffee"})
    assert [x["_id"] for x in r.json()["rows"]] == ["t1"]        # LIKE across the TEXT columns
    r = store_client.post("/api/data/transactions/rows",
                                json={"startRow": 0, "endRow": 100,
                                      "sortModel": [{"colId": "Amount", "sort": "asc"}]})
    assert [x["_id"] for x in r.json()["rows"]] == ["t3", "t1", "t2"]
    r = store_client.post("/api/data/transactions/rows",
                                json={"startRow": 1, "endRow": 2})
    assert r.json()["lastRow"] == 3 and len(r.json()["rows"]) == 1
    d = (store_client.get("/api/data/transactions/doc/t2")).json()["doc"]
    assert d["Description"] == "Paycheck" and d["Amount"] == 2000.0
    assert (store_client.get("/api/data/transactions/doc/nope")).status_code == 404


def test_deletions_browsable_read_only(store_client):
    deletions.log("transactions", [{"_id": "gone", "Description": "old"}], reason="test")
    r = store_client.post("/api/data/deletions/rows", json={"startRow": 0, "endRow": 10})
    row = r.json()["rows"][0]
    assert row["collection"] == "transactions" and "gone" in row["doc"]      # JSON shown as text
    r = store_client.post("/api/data/deletions/update",
                                json={"id": row["_id"], "field": "reason", "value": "x"})
    assert r.status_code == 403 and "read-only" in r.json()["error"]


def test_hidden_tables_404_everywhere(store_client):
    for table in ("users", "schema_version", "sqlite_master", "nope"):
        assert (store_client.get(f"/api/data/{table}/columns")).status_code == 404
        assert (store_client.post(f"/api/data/{table}/rows", json={})).status_code == 404
        assert (store_client.get(f"/api/data/{table}/doc/x")).status_code == 404
        assert (store_client.post(f"/api/data/{table}/update", json={})).status_code == 404


def test_autocat_edits_go_through_its_store(store_client):
    dbhelper.seed(autocat, [{"_id": "r1", "Category": "Food", "Description Contains": "cafe",
                                   "Amount Min": -100, "enabled": True}])
    r = store_client.post("/api/data/autocat/update",
                                json={"id": "r1", "field": "Amount Min", "value": "$-50"})
    assert r.json() == {"ok": True}
    r = store_client.post("/api/data/autocat/update",
                                json={"id": "r1", "field": "Amount Min", "value": "abc"})
    assert r.status_code == 400
    r = store_client.post("/api/data/autocat/update",
                                json={"id": "r1", "field": "id", "value": "x"})
    assert r.status_code == 400                                   # not an editable column
    row = autocat.get("r1")
    assert row["Amount Min"] == -50.0 and row["Category"] == "Food" and row["enabled"] is True
    r = store_client.post("/api/data/transactions/update",
                                json={"id": "t1", "field": "Description", "value": "x"})
    assert r.status_code == 403


def test_table_without_a_store_shows_raw_columns(store_client):
    # every table today has a store; the raw path is exercised through the datasource directly
    cols = datatable.columns("transactions")
    assert any(c["col"] == "account_number" and c["key"] == "Account #" for c in cols)
    assert datatable.store_for("nope") is None
    assert not datatable.exists("users") and datatable.exists("transactions")
    names = {t["name"] for t in datatable.tables()}
    assert "users" not in names and "transactions" in names


def test_djangos_tables_never_show(store_client):
    """auth_user, django_session and the rest share money.sqlite (ADR-0024) but are not
    the app's data: hidden from the page, the API and the store's table listing."""
    from app.store import database
    names = set(database.tables())
    assert not any(n.startswith(("auth_", "django_", "money_", "sqlite_")) for n in names)
    page = store_client.get("/data").text
    assert "auth_user" not in page and "django_session" not in page
    for t in ("auth_user", "django_session", "money_profile", "django_migrations"):
        assert store_client.get(f"/api/data/{t}/columns").status_code == 404
