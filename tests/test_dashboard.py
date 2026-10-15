"""Dashboard — the monthly aggregation must classify income/expense by Type,
matching the P&L and balance-sheet reports (bug #2: it used to bucket by sign of
Amount, counting transfers-in and refunds as income)."""

from datetime import datetime

from app.store.transactions import transactions
from tests import dbhelper


def test_monthly_income_is_type_based_not_sign_based(store_client):
    # A single fresh month with a positive transfer and a positive refund that
    # must NOT be read as income.
    dbhelper.seed(transactions, [
        {"_id": "m1", "Date": datetime(2025, 3, 1), "Type": "Income",
         "Amount": 2000.0, "Category": "Income"},
        {"_id": "m2", "Date": datetime(2025, 3, 2), "Type": "Expense",
         "Amount": -500.0, "Category": "Food"},
        {"_id": "m3", "Date": datetime(2025, 3, 3), "Type": "Transfer",
         "Amount": 1000.0, "Category": "Transfer"},      # positive, not income
        {"_id": "m4", "Date": datetime(2025, 3, 4), "Type": "Expense",
         "Amount": 50.0, "Category": "Food"},            # refund: positive expense
    ])

    r = store_client.get("/api/dashboard/monthly")
    assert r.status_code == 200
    d = r.json()
    i = d["labels"].index("2025-03")

    assert d["income"][i] == 2000.0          # transfer-in excluded (was 3050 when sign-based)
    assert d["spend"][i] == 450.0            # |-500 + 50| refund nets against spend
    assert d["net"][i] == 1550.0             # income − expense


def test_by_category_is_outflows_only_top_12(store_client):
    # base seed: Coffee -4.5 (Food), Rent -1500 (Housing), Paycheck +2000 (Income)
    d = (store_client.get("/api/dashboard/by-category")).json()
    assert d["categories"] == ["Housing", "Food"] and d["spend"] == [1500.0, 4.5]
    assert (store_client.get("/dashboard")).status_code == 200
