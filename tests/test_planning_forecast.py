"""Checking forecast (app/planning.forecast + /api/planning/forecast, Planning slice 9):
which accounts it starts from, the daily arithmetic with recurring events and variable
spend, the low point, the endpoint, and the Planner card."""

from datetime import UTC, date, datetime

import pytest

from app import planning
from app.store.accounts import accounts
from app.web import DomainError
from tests import dbhelper
from tests.test_planning_planner import _seed_year

TODAY = datetime(2026, 3, 10, tzinfo=UTC)


def test_checking_accounts_selects_open_visible_checking_only(store_db):
    dbhelper.seed(accounts, [
        {"_id": "a1", "Account": "MAIN CHECKING", "Category": "Checking Account", "Amount": 2239.35},
        {"_id": "a2", "Account": "Venmo", "Account Type": "Checking Account", "Amount": 100.0},
        {"_id": "a3", "Account": "Old checking", "Category": "Checking Account", "Amount": 50.0, "Status": "Closed"},
        {"_id": "a4", "Account": "Hidden", "Category": "Checking Account", "Amount": 50.0, "is_hidden": True},
        {"_id": "a5", "Account": "Visa", "Category": "Credit Card Debt", "Amount": -300.0},
        {"_id": "a6", "Account": "Brokerage", "Account Type": "Common Stock", "Amount": 9000.0},
    ])
    got = planning.checking_accounts()
    assert got == [{"name": "MAIN CHECKING", "balance": 2239.35}, {"name": "Venmo", "balance": 100.0}]


def test_project_arithmetic_events_and_low_point():
    income = [{"label": "Salary", "amount": 1000.0, "period_days": 14.0, "next_date": "2026-03-14", "cadence": "biweekly"}]
    bills = [{"label": "Rent", "amount": 900.0, "period_days": 30.44, "next_date": "2026-03-12", "cadence": "monthly"},
             {"label": "Irregular", "amount": 5.0, "period_days": None, "next_date": None, "cadence": "irregular"}]
    p = planning.project(500.0, date(2026, 3, 10), 10, income, bills, 20.0)
    assert len(p["series"]) == 11 and p["series"][0] == {"date": "2026-03-10", "balance": 500.0}
    assert p["series"][1]["balance"] == 480.0                              # one day of variable spend
    by = {e["date"]: e for e in p["events"]}
    assert by["2026-03-12"] == {"date": "2026-03-12", "label": "Rent", "amount": -900.0, "balance_after": -440.0}   # 500 − 2×20 − 900
    assert by["2026-03-14"]["amount"] == 1000.0 and by["2026-03-14"]["balance_after"] == 520.0               # −440 − 2×20 + 1000
    assert p["low"] == {"date": "2026-03-13", "balance": -460.0}            # the day before payday
    assert p["end_balance"] == 500.0 - 20.0 * 10 - 900.0 + 1000.0
    assert [e["label"] for e in p["events"]] == ["Rent", "Salary"]         # the irregular series never fires


def test_project_orders_income_before_bills_on_the_same_day():
    income = [{"label": "Pay", "amount": 100.0, "period_days": 7.0, "next_date": "2026-03-11"}]
    bills = [{"label": "Bill", "amount": 150.0, "period_days": 7.0, "next_date": "2026-03-11"}]
    p = planning.project(0.0, date(2026, 3, 10), 1, income, bills, 0.0)
    assert [(e["label"], e["balance_after"]) for e in p["events"]] == [("Pay", 100.0), ("Bill", -50.0)]
    assert p["low"]["balance"] == -50.0


def test_forecast_from_the_seeded_ledger(store_db):
    _seed_year()
    dbhelper.seed(accounts, [{"_id": "a1", "Account": "Checking", "Category": "Checking Account", "Amount": 4000.0}])
    f = planning.forecast(today=TODAY, days=60)
    assert f["start"] == "2026-03-10" and f["days"] == 60 and f["estimated"] is True
    assert f["start_balance"] == 4000.0 and f["accounts"] == ["Checking"]
    assert f["daily_variable"] > 0
    labels = {e["label"] for e in f["events"]}
    assert labels == {"Salary", "RENT PAYMENT"}                            # the two monthly series
    assert any(e["amount"] == 8000.0 for e in f["events"]) and any(e["amount"] == -2100.0 for e in f["events"])
    assert len(f["series"]) == 61 and f["low"]["balance"] <= f["start_balance"]
    assert f["end_balance"] == f["series"][-1]["balance"]
    for bad in (0, 367):
        with pytest.raises(DomainError):
            planning.forecast(today=TODAY, days=bad)


def test_forecast_endpoint_and_planner_card(store_client):
    dbhelper.seed(accounts, [{"_id": "a1", "Account": "Checking", "Category": "Checking Account", "Amount": 1200.0}])
    r = store_client.get("/api/planning/forecast?days=30")
    assert r.status_code == 200
    f = r.json()
    assert f["start_balance"] == 1200.0 and f["days"] == 30 and len(f["series"]) == 31 and f["estimated"] is True
    assert set(f) >= {"start", "accounts", "daily_variable", "series", "events", "low", "end_balance"}
    assert (store_client.get("/api/planning/forecast?days=0")).status_code == 400
    assert (store_client.get("/api/planning/forecast")).json()["days"] == 90
    html = (store_client.get("/planning/planner/2026")).text
    assert 'id="forecast"' in html and 'id="chart-forecast"' in html and 'id="forecast-events"' in html
    assert "Checking, next 90 days" in html and "/static/vendor/echarts.min.js" in html
    assert "planning-forecast.js" in html
