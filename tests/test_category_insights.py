"""Category Insights — the cashflow deep-dive (app/views/category_insights.py).
Uses the store-seeded transactions (tests/dbhelper.py):
  t1 2024-05-01 Food/Variable  -4.50   (Description "Coffee")
  t2 2024-05-02 Income/Income  2000.00
  t3 2024-05-03 Housing/Fixed  -1500.00
"""

from datetime import datetime

import pytest


def test_page_renders(store_client):
    r = store_client.get("/category-insights")
    assert r.status_code == 200 and "Category Insights" in r.text


def test_totals_grand_and_ordering(store_client):
    d = (store_client.get("/api/category-insights/data")).json()
    assert d["grand_total"] == 495.5                          # -4.5 + 2000 - 1500
    # Most-negative first (the report order).
    assert [g["name"] for g in d["groups"]] == ["Fixed", "Variable", "Income"]
    assert d["groups"][0] == {"name": "Fixed", "total": -1500.0}
    cats = {c["name"]: c["total"] for c in d["categories"]}
    assert cats == {"Housing": -1500.0, "Food": -4.5, "Income": 2000.0}


def test_group_filter_cascades_to_categories_and_txns(store_client):
    d = (store_client.get("/api/category-insights/data", params={"group": "Fixed"})).json()
    assert [c["name"] for c in d["categories"]] == ["Housing"]
    assert d["txn_count"] == 1
    assert d["transactions"][0]["category"] == "Housing"
    # Group panel itself still shows all groups (only date+search scope it).
    assert len(d["groups"]) == 3


def test_category_filter_narrows_transactions(store_client):
    d = (store_client.get("/api/category-insights/data", params={"category": "Food"})).json()
    assert d["txn_count"] == 1
    assert d["transactions"][0]["amount"] == -4.5


def test_date_range_filter(store_client):
    # Only 2024-05-02 → 2024-05-03 keeps t2 and t3.
    d = (store_client.get("/api/category-insights/data",
                          params={"start": "2024-05-02", "end": "2024-05-03"})).json()
    assert d["txn_count"] == 2
    assert d["grand_total"] == 500.0                          # 2000 - 1500


def test_description_search(store_client):
    d = (store_client.get("/api/category-insights/data", params={"q": "coffee"})).json()
    assert d["txn_count"] == 1
    assert d["transactions"][0]["description"] == "Coffee"
    assert d["grand_total"] == -4.5                           # scope follows the search


def test_none_label_round_trips_for_blank_group(store_client):
    from app.store.transactions import transactions
    from tests import dbhelper
    dbhelper.seed(transactions, [
        {"_id": "ng", "Date": datetime(2024, 5, 4), "Description": "Mystery", "Amount": -7.0}])
    d = (store_client.get("/api/category-insights/data", params={"group": "(none)"})).json()
    assert d["txn_count"] == 1 and d["transactions"][0]["category"] == "(none)"
    assert {g["name"] for g in d["groups"]} >= {"(none)", "Fixed"}
    page = (store_client.get("/category-insights")).text
    assert 'value="2024-05-01"' in page and 'value="2024-05-04"' in page   # ledger date span
