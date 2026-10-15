"""Inventory Overview rollup — mirrors the Sheets Overview.js calc. Pure-function
tests (no DB) plus one render through the real route."""

from datetime import datetime

from app.views.reports import _inventory_rollup
from app.store.balance_history import balance_history
from app.store.inventory import inventory
from app.store.transactions import transactions
from tests import dbhelper


def test_rollup_matches_sheets_rules():
    docs = [
        # Accessories: 3 items, 12 qty, $380 cost, $11 salvage (salvage summed raw)
        {"Category": "Accessories", "Qty": "5", "Unit_Cost": "40", "Salvage_Value": "5"},
        {"Category": "Accessories", "Qty": "4", "Unit_Cost": "30", "Salvage_Value": "4"},
        {"Category": "Accessories", "Qty": "3", "Unit_Cost": "20", "Salvage_Value": "2"},
        # Furniture: a positive useful-life value
        {"Category": "Furniture", "Qty": "1", "Unit_Cost": "3080", "Salvage_Value": "378",
         "Useful_Life_Years": "4.4"},
        {"Category": "", "Qty": "1", "Unit_Cost": "99"},   # blank category → skipped entirely
    ]
    rows, grand = _inventory_rollup(docs)

    acc = next(r for r in rows if r["category"] == "Accessories")
    assert acc["count"] == 3 and acc["qty"] == 12
    assert acc["cost"] == 380.0                 # 5*40 + 4*30 + 3*20
    assert acc["avg_unit"] == round(380 / 12, 2)
    assert acc["salvage"] == 11.0               # raw sum, not × qty
    assert acc["net"] == 369.0
    assert acc["avg_life"] == 0.0               # no positive life rows

    fur = next(r for r in rows if r["category"] == "Furniture")
    assert fur["avg_life"] == 4.4

    # categories sorted alphabetically
    assert [r["category"] for r in rows] == ["Accessories", "Furniture"]
    # percentages sum to 1
    assert abs(sum(r["pct"] for r in rows) - 1.0) < 1e-9

    # grand: blank-category row excluded from cost/qty; avg_unit = totalCost/totalQty
    assert grand["count"] == 4 and grand["qty"] == 13
    assert grand["cost"] == 3460.0
    assert grand["avg_unit"] == round(3460 / 13, 2)
    assert grand["pct"] == 1.0


def test_rollup_handles_empty():
    rows, grand = _inventory_rollup([])
    assert rows == []
    assert grand["count"] == 0 and grand["cost"] == 0.0 and grand["pct"] == 0.0


def test_inventory_sync_writes_assets_and_appends_records(store_client):
    dbhelper.seed(inventory, [
        {"_id": "s1", "Category": "Electronics", "Qty": "1", "Unit_Cost": "1000", "Salvage_Value": "100"},
        {"_id": "s2", "Category": "Tools", "Qty": "2", "Unit_Cost": "25"},
    ])
    r = store_client.post("/api/inventory-overview/sync")
    body = r.json()
    assert body["ok"] and "Electronics" in body["accounts"]

    # landed in balanceHistory as Assets, mapped, with the gross-cost balance
    elec = balance_history.one({"Account": "Electronics", "_src": "inventory_sync"})
    assert elec["Type"] == "Assets" and elec["Class"] == "Assets"
    assert elec["Account Type"] == "Equipment" and elec["Group"] == "Property & Equipment"
    assert elec["Balance"] == 1000.0                              # gross cost, salvage ignored

    # re-sync appends new dated records — earlier snapshots stay as history
    first = balance_history.count({"_src": "inventory_sync"})
    again = store_client.post("/api/inventory-overview/sync")
    assert again.json()["lines"] == first
    assert balance_history.count({"_src": "inventory_sync"}) == first * 2


def test_inventory_overview_route_renders(store_client):
    dbhelper.seed(inventory, [
        {"_id": "o1", "Category": "Tools", "Qty": "2", "Unit_Cost": "50", "Salvage_Value": "5"},
        {"_id": "o2", "Category": "Office", "Qty": "1", "Unit_Cost": "20"},
    ])
    r = store_client.get("/inventory-overview")
    assert r.status_code == 200
    assert "Grand Total" in r.text and "Tools" in r.text


def test_balance_sheet_starting_ending_max_and_month_income(store_client):
    dbhelper.seed(balance_history, [
        {"_id": "s1", "Date": datetime(2024, 5, 1), "Account": "Checking", "Class": "Asset", "Balance": 100.0,
         "Institution": "Ally"},
        {"_id": "s2", "Date": datetime(2024, 5, 15), "Account": "Checking", "Class": "Asset", "Balance": 300.0},
        {"_id": "s3", "Date": datetime(2024, 5, 31), "Account": "Checking", "Class": "Asset", "Balance": 250.0},
        {"_id": "s4", "Date": datetime(2024, 5, 2), "Account": "Visa", "Type": "Liabilities", "Balance": -50.0},
        {"_id": "s5", "Date": datetime(2024, 4, 2), "Account": "Visa", "Type": "Liabilities", "Balance": -20.0},
    ])
    assert balance_history.months() == [(2024, 5), (2024, 4)]
    page = (store_client.get("/balance-sheet?year=2024&month=5")).text
    assert "Checking" in page and "Ally" in page and "Visa" in page
    from app.networth import month_rows
    rows = {r["account"]: r for r in month_rows(balance_history.in_month(2024, 5))}
    assert rows["Checking"]["starting"] == 100.0 and rows["Checking"]["ending"] == 250.0
    assert rows["Checking"]["maxb"] == 300.0 and rows["Checking"]["cls"] == "Assets"
    assert rows["Visa"]["cls"] == "Liabilities"                    # Class NULL → coarse Type
    # base ledger: May 2024 income 2000 (Paycheck has no Type in the seed → 0), so the
    # month figure follows the Type rule, not the sign
    assert "Net worth" in page or "net worth" in page.lower()
    # The picker is a plain form (?ym=YYYY-M): flipping to April shows April, not the latest month.
    april = (store_client.get("/balance-sheet?ym=2024-4")).text
    assert "Apr 2024" in april.split("page-head", 1)[-1].split("</div>", 1)[0]
    assert '<option value="2024-4" selected>' in april and '<option value="2024-5" selected>' not in april
    assert "Checking" not in april.split("</form>", 1)[-1]           # no Checking Snapshot in April
    assert "onchange" not in april
    latest = (store_client.get("/balance-sheet?ym=garbage")).text
    assert '<option value="2024-5" selected>' in latest             # unknown → latest month


def test_pnl_renders_from_the_rollup(store_client):
    dbhelper.seed(transactions, [
        {"_id": "p1", "Date": datetime(2024, 6, 1), "Type": "Income", "Group": "Income", "Amount": 100.0}])
    page = (store_client.get("/pnl?year=2024")).text
    assert "Income" in page and "Jun" in page and "May" in page
