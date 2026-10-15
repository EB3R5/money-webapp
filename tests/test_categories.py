"""Categories page — the lookup-CRUD factory (app/lookups.py) behind /categories, on the
stores. Verifies the three registered contexts read their sections/items, and that edits
cascade onto the target table: the ADR-0006 backfill (ledger→transactions), the Balances
Type cascade, rename re-pointing, and the in-use delete guard with reassignment."""

import pytest

from app.store.account_categories import account_categories
from app.store.balance_history import balance_history
from app.store.categories import categories
from app.store.deletions import deletions
from app.store.inventory import inventory
from app.store.inventory_categories import inventory_categories
from app.store.transactions import transactions
from tests import dbhelper


def _seed_account_categories():
    dbhelper.seed_balances()
    dbhelper.seed(account_categories, [
        {"_id": "Checking Account", "Category": "Checking Account",
         "Group": "Current Assets", "Type": "Assets"},
        {"_id": "Savings Account", "Category": "Savings Account",
         "Group": "Current Assets", "Type": "Assets"},
        {"_id": "Credit Card Debt", "Category": "Credit Card Debt",
         "Group": "Current Liabilities", "Type": "Liabilities"},
    ])
    # A balance row that references one of them, so cascade has something to touch.
    balance_history.update("b2", {"Category": "Credit Card Debt"})


# --- read -------------------------------------------------------------------

def test_ledger_sections_and_options(store_client):
    r = store_client.get("/api/categories/ledger/sections")
    assert r.status_code == 200
    data = r.json()
    assert data["sections"] == ["Transport", "Variable"]
    # options seed the datalist editors with distinct existing values.
    assert "Type" in data["options"] and "Spend" in data["options"]["Type"]


def test_ledger_items_in_section(store_client):
    r = store_client.get("/api/categories/ledger", params={"section": "Variable"})
    items = r.json()["items"]
    assert [i["Category"] for i in items] == ["Food"]
    assert items[0]["Group"] == "Variable" and items[0]["_id"] == "Food"


def test_unknown_context_404(store_client):
    assert (store_client.get("/api/categories/nope/sections")).status_code == 404
    assert (store_client.post("/api/categories/nope/row", json={})).status_code == 404


def test_page_lists_every_context(store_client):
    page = (store_client.get("/categories")).text
    assert "Ledger Categories" in page and "Inventory Categories" in page


# --- cascade on edit (ADR-0006 backfill) ------------------------------------

def test_edit_group_cascades_onto_transactions(store_client):
    r = store_client.post("/api/categories/ledger/update",
                                json={"id": "Food", "field": "Group", "value": "Essentials"})
    assert r.json() == {"ok": True, "updated": 1}      # t1 has Category=Food
    assert (categories.get("Food"))["Group"] == "Essentials"
    assert (transactions.get("t1"))["Group"] == "Essentials"
    # A transaction with a different category is untouched.
    assert (transactions.get("t3"))["Group"] == "Fixed"


def test_balances_type_cascades_onto_balance_rows(store_client):
    _seed_account_categories()
    r = store_client.post("/api/categories/balances/update",
                                json={"id": "Credit Card Debt", "field": "Type", "value": "Debt"})
    assert r.json()["ok"] and r.json()["updated"] == 1
    b2 = balance_history.get("b2")
    assert b2["Type"] == "Debt" and b2["Account Type"] == "Credit"   # the granular kind is untouched
    assert (balance_history.get("b1")).get("Type") is None


# --- rename, add, delete ----------------------------------------------------

def test_rename_repoints_target_rows(store_client):
    r = store_client.post("/api/categories/ledger/update",
                                json={"id": "Food", "field": "Category", "value": "Groceries"})
    assert r.json()["ok"] and r.json()["updated"] == 1
    assert (transactions.get("t1"))["Category"] == "Groceries"
    clash = store_client.post("/api/categories/ledger/update",
                                    json={"id": "Auto", "field": "Category", "value": "Groceries"})
    assert clash.status_code == 409


def test_add_then_duplicate_rejected(store_client):
    ok = store_client.post("/api/categories/ledger/row",
                                 json={"Category": "Travel", "Group": "Variable", "Type": "Spend"})
    assert ok.json()["ok"] and ok.json()["row"]["Type"] == "Spend"
    assert (categories.get("Travel"))["Type"] == "Spend"
    dup = store_client.post("/api/categories/ledger/row",
                                  json={"Category": "Travel", "Group": "Variable"})
    assert dup.status_code == 409


def test_delete_guard_then_reassign(store_client):
    # Food is used by t1 → blocked.
    blocked = store_client.post("/api/categories/ledger/delete", json={"id": "Food"})
    assert blocked.status_code == 409 and blocked.json()["in_use"] == 1
    assert categories.get("Food")   # still there

    # Reassign t1 onto Auto, then delete succeeds and t1 inherits Auto's derived fields.
    ok = store_client.post("/api/categories/ledger/delete",
                                 json={"id": "Food", "reassign_to": "Auto"})
    assert ok.json()["ok"] and ok.json()["reassigned"] == 1
    assert categories.get("Food") is None
    t1 = transactions.get("t1")
    assert t1["Category"] == "Auto" and t1["Group"] == "Transport"
    logged = deletions.one({"collection": "categories"})
    assert logged and logged["doc"]["_id"] == "Food"


def _seed_inventory_categories():
    dbhelper.seed_inventory()          # inv1 (Category=Tools) and inv2 (Category=Office)
    dbhelper.seed(inventory_categories, [
        {"_id": "Tools", "Category": "Tools", "Group": "Tools & Equipment"},
        {"_id": "Office", "Category": "Office", "Group": "Home"},
        {"_id": "Kitchenware", "Category": "Kitchenware", "Group": "Kitchen"},
    ])


def test_inventory_sections_group_the_categories(store_client):
    _seed_inventory_categories()
    data = (store_client.get("/api/categories/inventory/sections")).json()
    assert set(data["sections"]) == {"Tools & Equipment", "Home", "Kitchen"}
    items = (store_client.get("/api/categories/inventory",
                                    params={"section": "Kitchen"})).json()["items"]
    assert [i["Category"] for i in items] == ["Kitchenware"]


def test_inventory_rename_cascades_to_items(store_client):
    _seed_inventory_categories()
    r = store_client.post("/api/categories/inventory/update",
                                json={"id": "Tools", "field": "Category", "value": "Hand Tools"})
    assert r.json()["ok"] and r.json()["updated"] == 1          # inv1 re-pointed
    assert (inventory.get("inv1"))["Category"] == "Hand Tools"


def test_inventory_group_edit_does_not_touch_items(store_client):
    _seed_inventory_categories()
    r = store_client.post("/api/categories/inventory/update",
                                json={"id": "Office", "field": "Group", "value": "Apparel"})
    assert r.json() == {"ok": True, "updated": 0}               # Group does not cascade
    assert (inventory_categories.get("Office"))["Group"] == "Apparel"
    assert (inventory.get("inv2"))["Category"] == "Office"   # item left untouched


def test_inventory_metadata_columns_editable_no_cascade(store_client):
    _seed_inventory_categories()
    # Subcategory / Classification are editable columns on the inventory context...
    opts = (store_client.get("/api/categories/inventory/sections")).json()["options"]
    assert {"Group", "Subcategory", "Classification"} <= set(opts)
    # ...but editing them is descriptive only — never cascades onto the items.
    r = store_client.post("/api/categories/inventory/update",
                                json={"id": "Tools", "field": "Subcategory", "value": "Power Tools"})
    assert r.json() == {"ok": True, "updated": 0}
    assert (inventory_categories.get("Tools"))["Subcategory"] == "Power Tools"
    assert (inventory.get("inv1")).get("Subcategory") is None


def test_inventory_delete_guard_then_reassign(store_client):
    _seed_inventory_categories()
    blocked = store_client.post("/api/categories/inventory/delete", json={"id": "Tools"})
    assert blocked.status_code == 409 and blocked.json()["in_use"] == 1
    ok = store_client.post("/api/categories/inventory/delete",
                                 json={"id": "Tools", "reassign_to": "Kitchenware"})
    assert ok.json()["ok"] and ok.json()["reassigned"] == 1
    assert (inventory.get("inv1"))["Category"] == "Kitchenware"


def test_delete_unused_succeeds(store_client):
    store_client.post("/api/categories/ledger/row",
                            json={"Category": "Gifts", "Group": "Variable"})
    r = store_client.post("/api/categories/ledger/delete", json={"id": "Gifts"})
    assert r.json() == {"ok": True, "deleted": 1, "reassigned": 0}
    assert categories.get("Gifts") is None
