"""Budget pivot — Budget-vs-Actual cross-version matrix (app/budgets.build_version_pivot +
/budgets/pivot). Rows = Group (sectioned by kind); each version has Budget + Actual columns,
Actual aggregated from transactions and conditionally formatted by assess()."""

from datetime import UTC, datetime

from app import budgets as engine
from app.store.budget_lines import budget_lines
from app.store.budgets import budgets
from app.store.categories import categories
from app.store.transactions import transactions
from tests import dbhelper


def seed_budgets():
    """Two versions over a Jan/Feb ledger; shared with the lifecycle tests."""
    dbhelper.seed(categories, [
        {"_id": "Salary", "Category": "Salary", "Group": "Salary", "Type": "Income"},
        {"_id": "Rent", "Category": "Rent", "Group": "Rent", "Type": "Expense"},
        {"_id": "Groceries", "Category": "Groceries", "Group": "Food", "Type": "Expense"},
    ])
    # Actuals: Jan has Food/Rent/Salary activity; Feb has Food plus Dining, which no
    # version budgets (an unbudgeted group in Feb only).
    dbhelper.seed(transactions, [
        {"_id": "x1", "Date": datetime(2026, 1, 15), "Group": "Food", "Amount": -1455.0, "Type": "Expense"},
        {"_id": "x2", "Date": datetime(2026, 1, 5), "Group": "Rent", "Amount": -2100.0, "Type": "Expense"},
        {"_id": "x3", "Date": datetime(2026, 1, 1), "Group": "Salary", "Amount": 8000.0, "Type": "Income"},
        {"_id": "x4", "Date": datetime(2026, 2, 15), "Group": "Food", "Amount": -900.0, "Type": "Expense"},
        {"_id": "x5", "Date": datetime(2026, 2, 20), "Group": "Dining", "Amount": -60.0, "Type": "Expense"},
    ])
    dbhelper.seed(budgets, [
        {"_id": "bud_a", "budgetId": "BUD001", "versionName": "Baseline", "month": "2026-01",
         "status": "saved", "_created_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"_id": "bud_b", "budgetId": "BUD002", "versionName": "Tight", "month": "2026-02",
         "status": "saved", "_created_at": datetime(2026, 2, 1, tzinfo=UTC)},
    ])
    dbhelper.seed(budget_lines, [
        {"budget": "bud_a", "position": 0, "group": "Salary", "amount": 8000},
        {"budget": "bud_a", "position": 1, "group": "Food", "amount": 1200},
        {"budget": "bud_a", "position": 2, "group": "Rent", "amount": 2100},
        {"budget": "bud_b", "position": 0, "group": "Salary", "amount": 8000},
        {"budget": "bud_b", "position": 1, "group": "Food", "amount": 900},
        {"budget": "bud_b", "position": 2, "group": "Rent", "amount": 2100},
    ])


def _row(table, group):
    for s in table["sections"]:
        for r in s["rows"]:
            if r["group"] == group:
                return r
    raise AssertionError(f"no row for {group}")


def test_versions_and_sections(store_db):
    seed_budgets()
    data = engine.build_version_pivot()
    assert [v["key"] for v in data["versions"]] == ["bud_a", "bud_b"]
    assert {s["label"] for s in data["table"]["sections"]} == {"Income", "Expense"}


def test_actuals_aggregated_from_transactions(store_db):
    seed_budgets()
    t = (engine.build_version_pivot())["table"]
    food = _row(t, "Food")
    assert food["budget"] == {"bud_a": 1200.0, "bud_b": 900.0}
    assert food["actual"] == {"bud_a": -1455.0, "bud_b": -900.0}   # real spend, by month
    # Per-version column totals carry both measures.
    assert t["totals"]["bud_a|b"] == 11300.0 and t["totals"]["bud_a|a"] == 4445.0
    assert t["totals"]["bud_b|a"] == -960.0                       # includes the unbudgeted Dining spend
    assert t["totals"]["bud_b|b"] == 11000.0                      # budget total unchanged by it


def test_conditional_formatting_classes(store_db):
    seed_budgets()
    t = (engine.build_version_pivot())["table"]
    # Food Jan: 1455 vs 1200 budget → ~21% over (expense, unfavorable) = High.
    assert _row(t, "Food")["fmt"]["bud_a"] == "bva-bad2"
    # Food Feb: 900 vs 900 → on target.
    assert _row(t, "Food")["fmt"]["bud_b"] == "bva-ok"
    # Rent Feb: no actual (0) vs 2100 → way under an expense = favorable.
    assert _row(t, "Rent")["fmt"]["bud_b"] == "bva-good"
    # Salary Feb: 0 actual vs 8000 income target → critically under = unfavorable.
    salary = _row(t, "Salary")
    assert salary["kind"] == "income" and salary["fmt"]["bud_b"] == "bva-bad3"


def test_unbudgeted_group_appears_per_version(store_db):
    seed_budgets()
    t = (engine.build_version_pivot())["table"]
    dining = _row(t, "Dining")
    assert dining["kind"] == "expense"
    assert dining["budget"] == {"bud_b": 0.0} and dining["actual"] == {"bud_b": -60.0}
    assert dining["fmt"] == {"bud_b": "bva-unb"}                  # no verdict, the unbudgeted marker
    assert "bud_a" not in dining["budget"]                         # no Jan activity → "–" cells


def test_pivot_page_renders(store_client):
    seed_budgets()
    r = store_client.get("/budgets/pivot")
    assert r.status_code == 200
    assert "Budget Pivot" in r.text and "Budget" in r.text and "Actual" in r.text
    assert "bva-" in r.text                                        # conditional-format classes present
    assert 'class="num bva-unb">' in r.text and "Dining" in r.text  # unbudgeted actual cell rendered
    assert '<span class="bva-unb">unbudgeted</span>' in r.text     # legend entry


def test_pivot_empty_when_no_budgets(store_client):
    data = engine.build_version_pivot()
    assert data["versions"] == []
    r = store_client.get("/budgets/pivot")
    assert r.status_code == 200 and "No budgets yet" in r.text
