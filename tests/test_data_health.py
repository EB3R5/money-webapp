"""App health / activity — the status snapshot (app/data_health.py) over the store tables
+ /activity page and /api/health endpoint. Uses the ledger seed (2024-05, all categorized)."""

from datetime import UTC, datetime

from app import data_health as H
from app.store.accounts import accounts
from app.store.app_health import app_health
from app.store.balance_history import balance_history
from app.store.budgets import budgets
from app.store.inventory import inventory
from app.store.transactions import transactions
from tests import dbhelper


def test_compute_health_snapshot_and_persist(store_client):
    dbhelper.seed(balance_history, [
        {"_id": "b1", "Date": datetime(2024, 1, 2), "Account": "Checking", "Balance": 100.0},
        {"_id": "b2", "Date": datetime(2024, 2, 2), "Account": "Visa", "Balance": -50.0}])
    snap = H.compute_health()
    secs = {s["key"]: s for s in snap["sections"]}
    assert secs["transactions"]["count"] == 3                 # t1, t2, t3
    assert secs["balances"]["count"] == 2 and secs["balances"]["current_through"] == datetime(2024, 2, 2)
    # Reports are current through the latest transaction date (2024-05-03).
    assert snap["reports_current_through"] == datetime(2024, 5, 3)
    # All seeded transactions have a Category → nothing needs categorizing.
    assert snap["needs_categorization"] == 0
    assert snap["simplefin"]["configured"] is False and snap["simplefin"]["running"] is False
    # Persisted to app_health/current for external readers.
    cur = app_health.get("current")
    assert cur is not None and cur["needs_categorization"] == 0 and len(cur["sections"]) == len(H.SECTIONS)
    H.compute_health()
    assert app_health.count() == 1                       # upsert, not append


def test_current_through_covers_every_section(store_client):
    """Every line item gets a current-through: a date column where the data has one
    (inventory Date_Moved, budgets month → its last day), the last-updated timestamp where
    it doesn't — and none of those move the ledger-driven top line."""
    edited = datetime(2026, 6, 20, 12, 0)
    dbhelper.seed(inventory, [{"_id": "i1", "Item_Name": "Drill", "Date_Moved": "2026-04-22"}])
    dbhelper.seed(budgets, [{"_id": "b1", "month": "2026-06", "_created_at": edited}])
    dbhelper.seed(accounts, [{"_id": "a1", "Account": "Checking", "_created_at": edited}])
    snap = H.compute_health()
    secs = {s["key"]: s for s in snap["sections"]}
    assert secs["inventory"]["current_through"] == datetime(2026, 4, 22)
    assert secs["budgets"]["current_through"] == datetime(2026, 6, 30)   # month → last day
    assert secs["accounts"]["current_through"] == edited                 # fallback
    assert secs["autocat"]["count"] == 0 and secs["autocat"]["collection"] == "autocat"
    # Forward-dated budgets/edits must not move "reports current through".
    assert snap["reports_current_through"] == datetime(2024, 5, 3)


def test_mixed_naive_and_aware_timestamps_compare(store_client):
    """Exported rows hold naive UTC timestamps, app-written rows hold +00:00 ones; the
    section max must compare them instead of raising (the /activity 500)."""
    dbhelper.seed(accounts, [
        {"_id": "a1", "Account": "Checking", "_edited_at": datetime(2026, 6, 20, 12, 0),
         "_created_at": datetime(2026, 6, 21, 9, 0, tzinfo=UTC)}])
    secs = {s["key"]: s for s in (H.compute_health())["sections"]}
    assert secs["accounts"]["last_updated"] == datetime(2026, 6, 21, 9, 0)
    assert H._as_datetime("2026-06-20T12:00:00") < H._as_datetime("2026-06-21T09:00:00+00:00")


def test_needs_categorization_counts_blanks(store_client):
    dbhelper.seed(transactions, [
        {"_id": "u1", "Date": datetime(2024, 6, 1), "Amount": -5, "Category": ""},
        {"_id": "u2", "Date": datetime(2024, 6, 2), "Amount": -6},          # NULL Category
    ])
    assert (H.compute_health())["needs_categorization"] == 2


def test_activity_page_renders(store_client):
    r = store_client.get("/activity")
    assert r.status_code == 200 and "App Activity" in r.text
    assert "Not configured" in r.text                          # feed block without an Access URL


def test_health_api_is_json_safe(store_client):
    d = (store_client.get("/api/health")).json()
    assert isinstance(d["generated_at"], str)
    assert isinstance(d["reports_current_through"], str)
    assert any(s["key"] == "transactions" for s in d["sections"])
    assert d["simplefin"]["budget"] > 0
