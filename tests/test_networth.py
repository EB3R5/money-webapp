"""Net worth has one owner (ADR-0021, D2): the balance sheet and the Planning pages read the
same figure from app.networth. Pure-function tests plus the as-of-month lookup, its fallback,
the delta, and a check that the Balance Sheet page still shows the shared number."""

from datetime import datetime

from app import networth
from app.store.balance_history import balance_history
from tests import dbhelper

SNAPSHOTS = [
    {"_id": "s1", "Date": datetime(2024, 5, 1), "Account": "Checking", "Class": "Asset", "Balance": 100.0,
     "Institution": "Ally"},
    {"_id": "s2", "Date": datetime(2024, 5, 15), "Account": "Checking", "Class": "Asset", "Balance": 300.0},
    {"_id": "s3", "Date": datetime(2024, 5, 31), "Account": "Checking", "Class": "Asset", "Balance": 250.0},
    {"_id": "s4", "Date": datetime(2024, 5, 2), "Account": "Visa", "Type": "Liabilities", "Balance": -50.0},
    {"_id": "s5", "Date": datetime(2024, 5, 20), "Account": "Brokerage", "Class": "Equity", "Balance": 1000.0},
    {"_id": "s6", "Date": datetime(2024, 4, 2), "Account": "Visa", "Type": "Liabilities", "Balance": -20.0},
    {"_id": "s7", "Date": datetime(2024, 4, 9), "Account": "Checking", "Class": "Asset", "Balance": 80.0},
]


def test_canon_class_folds_class_and_type_labels():
    assert networth.canon_class("Asset") == networth.canon_class("Assets") == "Assets"
    assert networth.canon_class("Liability") == networth.canon_class("liabilities") == "Liabilities"
    assert networth.canon_class("Equity") == "Equity"
    assert networth.canon_class(None) == "(unclassified)"


def test_summarize_assets_plus_equity_minus_abs_liabilities():
    rows = [{"cls": "Assets", "ending": 250.0}, {"cls": "Equity", "ending": 1000.0},
            {"cls": "Liabilities", "ending": -50.0}, {"cls": "(unclassified)", "ending": 999.0}]
    assert networth.summarize(rows) == {"assets": 1250.0, "liabilities": 50.0, "net_worth": 1200.0}


def test_prev_month_wraps_the_year():
    assert networth.prev_month("2026-01") == "2025-12"
    assert networth.prev_month("2026-10") == "2026-09"


def test_net_worth_at_uses_each_accounts_ending_snapshot(store_db):
    dbhelper.seed(balance_history, SNAPSHOTS)
    may = networth.net_worth_at("2024-05")
    assert may == {"assets": 1250.0, "liabilities": 50.0, "net_worth": 1200.0,
                   "as_of": "2024-05", "exact": True}


def test_net_worth_at_falls_back_to_the_latest_earlier_month(store_db):
    dbhelper.seed(balance_history, SNAPSHOTS)
    sept = networth.net_worth_at("2024-09")                 # no Snapshots after May
    assert sept["as_of"] == "2024-05" and sept["exact"] is False
    assert sept["net_worth"] == 1200.0
    assert networth.net_worth_at("2024-03") is None          # nothing precedes April


def test_net_worth_delta_against_the_month_before_the_measured_one(store_db):
    dbhelper.seed(balance_history, SNAPSHOTS)
    d = networth.net_worth_delta("2024-05")
    assert d["value"] == 1200.0 and d["prev"] == 60.0 and d["delta"] == 1140.0
    assert d["prev_as_of"] == "2024-04"
    # A fallback month measures against the month before its as_of, not before the request.
    d2 = networth.net_worth_delta("2024-09")
    assert d2["as_of"] == "2024-05" and d2["prev_as_of"] == "2024-04" and d2["delta"] == 1140.0
    first = networth.net_worth_delta("2024-04")
    assert first["delta"] is None and first["prev"] is None


def test_balance_sheet_shows_the_shared_figure(store_client):
    dbhelper.seed(balance_history, SNAPSHOTS)
    page = (store_client.get("/balance-sheet?year=2024&month=5")).text
    expected = networth.net_worth_at("2024-05")
    head = page.split("summary-cards", 1)[1].split("</div>", 1)[0]
    assert '<span class="v">1,200</span>' in head                 # net worth
    assert "assets 1,250 · liabilities 50" in head
    assert expected["net_worth"] == 1200.0
