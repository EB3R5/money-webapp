"""Credit — registry/score/activity in their own stores; balances + payments derived from
the shared balance history / transactions stores; Summary + Strategy computed."""

from datetime import UTC, datetime, timedelta

import pytest

from app import credit
from app.store.balance_history import balance_history
from app.store.transactions import transactions
from app.web import DomainError
from tests import dbhelper


def test_account_balance_synced_via_alias(store_client):
    # Registry stores the limit; balance comes live from balanceHistory via the alias.
    dbhelper.seed(balance_history, [
        {"_id": "cb1", "Date": datetime(2026, 1, 1), "Account": "EVERYDAY CARD (1234)", "Balance": -200.0},
        {"_id": "cb2", "Date": datetime(2026, 3, 1), "Account": "EVERYDAY CARD (1234)", "Balance": -300.0},
    ])
    credit.add_account({"name": "Everyday Card", "type": "Credit Card", "credit_limit": 500,
                              "apr": 24.9, "status": "Active",
                              "balance_account": "EVERYDAY CARD (1234)"})
    acct = (credit.list_accounts())[0]
    assert acct["balance_as_of"] == "2026-03-01"
    assert acct["credit_limit"] == 500.0
    assert acct["apr"] == 0.249                 # percent → fraction
    assert acct["balance"] == 300.0             # latest snapshot, abs
    assert acct["utilization"] == 0.6           # 300 / 500


def test_apr_and_limit_validation(store_client):
    with pytest.raises(DomainError):
        credit.add_account({"name": "", "credit_limit": 100})
    with pytest.raises(DomainError):
        credit.add_account({"name": "Bad", "credit_limit": "abc"})


def test_score_log_and_summary_progress(store_client):
    credit.add_score({"date": "2025-01-01", "bureau": "Equifax", "score": 546})
    credit.add_score({"date": "2026-01-01", "bureau": "Equifax", "score": 620})
    credit.set_config({"score_target": 800})
    s = (credit.credit_summary())["score"]
    assert s["starting"] == 546 and s["current"] == 620
    assert s["gained"] == 74
    assert s["target"] == 800
    assert s["milestone"] == "Fair"                       # >=580
    assert "Good" in s["next_milestone"]


def test_activity_falls_off_derived(store_client):
    credit.add_activity({"date": "2025-06-15", "category": "Hard Inquiry",
                               "creditor": "Goldman"})
    credit.add_activity({"date": "2024-01-01", "category": "Soft Inquiry"})
    rows = {r["category"]: r for r in credit.list_activity()}
    assert rows["Hard Inquiry"]["falls_off"] == "2027-06-15"   # +2 years
    assert rows["Soft Inquiry"]["falls_off"] is None           # 0 years → none


def test_summary_utilization_and_payments(store_client):
    dbhelper.seed(balance_history, [
        {"_id": "cb1", "Date": datetime(2026, 1, 1), "Account": "Card A", "Balance": -400.0}])
    credit.add_account({"name": "Card A", "credit_limit": 1000, "status": "Active",
                              "balance_account": "Card A"})
    # a recent credit-card payment in the shared transactions
    dbhelper.seed(transactions, [
        {"_id": "pay1", "Date": datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
         "Group": "Credit Card", "Type": "Expense", "Amount": -150.0, "Account": "Chase"}])
    s = credit.credit_summary()
    assert s["accounts"]["overall_util"] == 0.4      # 400 / 1000
    assert s["payments"]["d30"] == 150.0
    assert s["payments"]["all"] == 150.0


def test_strategy_payoff_avalanche_order(store_client):
    dbhelper.seed(balance_history, [
        {"_id": "cbLow", "Date": datetime(2026, 1, 1), "Account": "Low APR", "Balance": -1000.0},
        {"_id": "cbHigh", "Date": datetime(2026, 1, 1), "Account": "High APR", "Balance": -500.0},
    ])
    credit.add_account({"name": "Low APR", "credit_limit": 2000, "apr": 12,
                              "min_payment": 50, "status": "Active", "balance_account": "Low APR"})
    credit.add_account({"name": "High APR", "credit_limit": 2000, "apr": 28,
                              "min_payment": 50, "status": "Active", "balance_account": "High APR"})
    payoff = (credit.strategy())["payoff"]["rows"]
    assert payoff[0]["name"] == "High APR"   # highest APR first (avalanche)
    assert payoff[0]["priority"] == 1
    assert payoff[0]["months"] is not None and payoff[0]["months"] > 0


def test_credit_page_and_api_render(store_client):
    credit.add_score({"date": "2025-01-01", "bureau": "Equifax", "score": 546})
    r = store_client.get("/credit")
    assert r.status_code == 200
    assert "Credit" in r.text and "utilization scenarios" in r.text.lower()
    body = (store_client.get("/api/credit/summary")).json()
    assert "score" in body and "accounts" in body and "fico" in body
