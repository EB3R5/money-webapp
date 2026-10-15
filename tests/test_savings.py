"""Metrics — Savings section, a faithful port of the Savings Foundation sheet. Category
Mapping roles drive income (INCOME) and savings (SAVINGS, summed as |amount|, no withdrawal
netting); the rate is per-year; goals progress against the year's pooled total."""

from datetime import datetime

import pytest

from app import savings
from app.store.transactions import transactions
from app.web import DomainError
from tests import dbhelper

YEAR = 2027


def _seed_year():
    # One clean year: $4000 income, $1000 deposit (SAVINGS), a -$200 withdrawal and food
    # (both IGNORE by default) → savings = 1000 (abs of deposit, withdrawal NOT netted).
    dbhelper.seed(transactions, [
        {"_id": "mx1", "Date": datetime(YEAR, 1, 5), "Type": "Income",
         "Category": "Paycheck", "Group": "Income", "Amount": 4000.0},
        {"_id": "mx2", "Date": datetime(YEAR, 1, 6), "Type": "Transfer",
         "Category": "Investing Deposit", "Group": "Deposit", "Amount": 1000.0},
        {"_id": "mx3", "Date": datetime(YEAR, 1, 7), "Type": "Transfer",
         "Category": "Investing Withdrawal", "Group": "Withdrawal", "Amount": -200.0},
        {"_id": "mx4", "Date": datetime(YEAR, 1, 8), "Type": "Expense",
         "Category": "Food", "Group": "Variable", "Amount": -50.0},
    ])
    savings.sync_mapping()   # seed roles: Paycheck→INCOME, Investing Deposit→SAVINGS, rest IGNORE


def test_sync_mapping_seeds_roles(store_client):
    _seed_year()
    roles = {m["category"]: m["role"] for m in savings.list_mapping()}
    assert roles["Paycheck"] == "INCOME"            # Type=="Income"
    assert roles["Investing Deposit"] == "SAVINGS"  # default savings category
    assert roles["Investing Withdrawal"] == "IGNORE"
    assert roles["Food"] == "IGNORE"


def test_savings_rate_math_no_withdrawal_netting(store_client):
    _seed_year()
    data = savings.savings_rate_by_month(YEAR)
    jan = next(r for r in data["rows"] if r["month"] == f"{YEAR}-01")
    assert jan["income"] == 4000.0
    assert jan["savings"] == 1000.0    # |deposit| only — withdrawal is IGNORE, not subtracted
    assert jan["target"] == 800.0      # 4000 * 0.20 default
    assert jan["gap"] == 200.0
    assert jan["rate"] == 0.25


def test_role_change_and_income_override(store_client):
    _seed_year()
    # Tag the withdrawal as SAVINGS too → savings becomes 1000 + |−200| = 1200 (abs, additive).
    savings.set_mapping_role({"category": "Investing Withdrawal", "role": "SAVINGS"})
    # Override monthly income to 5000.
    savings.set_savings_config({"income_override": 5000})
    jan = next(r for r in (savings.savings_rate_by_month(YEAR))["rows"]
               if r["month"] == f"{YEAR}-01")
    assert jan["income"] == 5000.0
    assert jan["savings"] == 1200.0
    assert jan["target"] == 1000.0     # 5000 * 0.20


def test_config_accepts_percent(store_client):
    out = savings.set_savings_config({"target_rate": 25})
    assert out["config"]["target_rate"] == 0.25
    assert (savings.get_savings_config())["target_rate"] == 0.25


def test_config_scenario_rates(store_client):
    out = savings.set_savings_config({"scenario_rates": [10, 20, 30]})
    assert out["config"]["scenario_rates"] == [0.1, 0.2, 0.3]


def test_albert_savings_category_seeds_savings(store_client):
    # Albert is a savings app — its outflows are valid contributions, summed as |amount|.
    dbhelper.seed(transactions, [
        {"_id": "alb", "Date": datetime(YEAR, 2, 1), "Type": "Expense",
         "Category": "Savings", "Group": "Savings", "Amount": -19.99}])
    savings.sync_mapping()
    roles = {m["category"]: m["role"] for m in savings.list_mapping()}
    assert roles["Savings"] == "SAVINGS"
    feb = next(r for r in (savings.savings_rate_by_month(YEAR))["rows"]
               if r["month"] == f"{YEAR}-02")
    assert feb["savings"] == 19.99


def test_savings_history_is_cumulative(store_client):
    dbhelper.seed(transactions, [
        {"_id": "h1", "Date": datetime(2026, 1, 3), "Type": "Transfer",
         "Category": "Investing Deposit", "Amount": 500.0},
        {"_id": "h2", "Date": datetime(2026, 2, 3), "Type": "Transfer",
         "Category": "Investing Deposit", "Amount": 300.0},
    ])
    savings.sync_mapping()
    hist = savings.savings_history()
    by_month = {r["month"]: r for r in hist}
    assert by_month["2026-01"]["balance"] == 500.0
    assert by_month["2026-02"]["balance"] == 800.0   # cumulative


def test_projections_forward_uses_avg_monthly(store_client):
    _seed_year()   # 2027: savings 1000 in one month → avg_monthly 1000, balance 1000
    proj = savings.projections(YEAR)
    assert proj["balance_now"] == 1000.0
    assert proj["avg_monthly"] == 1000.0
    assert len(proj["forward"]) == savings.PROJECTION_MONTHS
    assert proj["forward"][0]["projected"] == 2000.0   # 1000 + 1000
    assert proj["forward"][1]["projected"] == 3000.0


def test_rate_scenarios_per_rate(store_client):
    _seed_year()   # income 4000 over 1 month → avg_income 4000
    scen = savings.rate_scenarios(YEAR)
    assert scen["avg_income"] == 4000.0
    assert len(scen["scenarios"]) == 5               # default 10/15/20/25/30
    s10 = next(s for s in scen["scenarios"] if s["label"] == "10%")
    assert len(s10["balances"]) == savings.SCENARIO_MONTHS
    assert s10["balances"][0] == 1400.0              # 1000 + 4000*0.10


def test_goal_crud_and_derivation(store_client):
    _seed_year()   # total saved (year) = 1000, avg monthly = 1000
    gid = (savings.add_goal({"name": "Emergency fund", "target_amount": 2000}))["id"]

    g = next(x for x in savings.list_goals(YEAR) if x["id"] == gid)
    assert g["current_balance"] == 1000.0    # pooled year total
    assert g["remaining"] == 1000.0
    assert g["pct"] == 0.5

    savings.update_goal({"id": gid, "target_amount": 1000})
    g = next(x for x in savings.list_goals(YEAR) if x["id"] == gid)
    assert g["remaining"] == 0.0 and g["on_track"] == "achieved"

    savings.delete_goal({"id": gid})
    assert all(x["id"] != gid for x in savings.list_goals(YEAR))


def test_add_goal_rejects_bad_input(store_client):
    with pytest.raises(DomainError):
        savings.add_goal({"name": "", "target_amount": 100})
    with pytest.raises(DomainError):
        savings.add_goal({"name": "x", "target_amount": -5})


def test_set_mapping_role_validates(store_client):
    with pytest.raises(DomainError):
        savings.set_mapping_role({"category": "Food", "role": "NONSENSE"})


def test_metrics_page_renders(store_client):
    _seed_year()
    r = store_client.get("/metrics?year=" + str(YEAR))
    assert r.status_code == 200
    assert "Savings" in r.text and "Category Mapping" in r.text

    body = (store_client.get("/api/metrics/savings?year=" + str(YEAR))).json()
    assert body["year"] == YEAR
    assert "rows" in body and "summary" in body and "config" in body


def test_goal_balance_from_account_typed_or_pooled(store_client):
    """ADR-0023 follow-up #182: a goal's balance is the typed figure, else the linked
    account's current amount, else the pooled total; the monthly contribution rides along."""
    from app.store.accounts import accounts
    from tests import dbhelper
    dbhelper.seed(accounts, [{"_id": "sv", "Account": "Ally Savings", "Category": "Savings", "Amount": 4200.0}])
    r = store_client.post("/api/metrics/savings/goals", json={
        "name": "Trip", "target_amount": 3000, "monthly_contribution": "150", "balance_account": "Ally Savings"})
    assert r.status_code == 200
    gid = r.json()["id"]
    [g] = [x for x in (store_client.get("/api/metrics/savings")).json()["goals"] if x["id"] == gid]
    assert g["current_balance"] == 4200.0 and g["balance_source"] == "account"
    assert g["monthly_contribution"] == 150.0 and g["on_track"] == "achieved"
    r = store_client.post("/api/metrics/savings/goals/update", json={"id": gid, "balance_override": "900"})
    assert r.json()["ok"]
    [g] = [x for x in (store_client.get("/api/metrics/savings")).json()["goals"] if x["id"] == gid]
    assert g["current_balance"] == 900.0 and g["balance_source"] == "typed" and g["remaining"] == 2100.0
    r = store_client.post("/api/metrics/savings/goals/update", json={"id": gid, "balance_override": "", "balance_account": ""})
    [g] = [x for x in (store_client.get("/api/metrics/savings")).json()["goals"] if x["id"] == gid]
    assert g["balance_source"] == "pooled"
    for bad in ({"id": gid, "balance_account": "Nope"}, {"id": gid, "balance_override": -1}, {"id": gid, "monthly_contribution": -5}):
        assert (store_client.post("/api/metrics/savings/goals/update", json=bad)).status_code == 400
    html = (store_client.get("/metrics")).text
    assert 'id="goal-per"' in html and 'id="goal-account"' in html and '<option value="Ally Savings">' in html
    assert 'data-edit-goal="' + gid + '"' in html and "pooled savings" in html
