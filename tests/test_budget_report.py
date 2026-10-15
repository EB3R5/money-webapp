"""Budget vs Actual report (app/budgets.build_report + /budgets/{id}/report): the row
universe is the union of budget lines and groups with activity in the month, each row
tagged by which side it came from, with the summary totals reflecting real spend."""

from datetime import UTC, datetime

from app import budgets as engine
from app.store.budget_lines import budget_lines
from app.store.budgets import budgets
from app.store.categories import categories
from app.store.transactions import transactions
from tests import dbhelper


def _seed():
    """One month: Food (budgeted, spent), Rent (budgeted, no spend), Dining (spent, no line),
    Salary income (spent, no line), plus a zero-amount line and a blank-Group row."""
    dbhelper.seed(categories, [
        {"_id": "Salary", "Category": "Salary", "Group": "Salary", "Type": "Income"},
        {"_id": "Rent", "Category": "Rent", "Group": "Rent", "Type": "Expense"},
        {"_id": "Groceries", "Category": "Groceries", "Group": "Food", "Type": "Expense"},
        {"_id": "Dining", "Category": "Dining", "Group": "Dining", "Type": "Expense"},
    ])
    dbhelper.seed(transactions, [
        {"_id": "x1", "Date": datetime(2026, 1, 15), "Group": "Food", "Amount": -1455.0, "Type": "Expense"},
        {"_id": "x2", "Date": datetime(2026, 1, 20), "Group": "Dining", "Amount": -210.0, "Type": "Expense"},
        {"_id": "x3", "Date": datetime(2026, 1, 1), "Group": "Salary", "Amount": 8000.0, "Type": "Income"},
        {"_id": "x4", "Date": datetime(2026, 2, 15), "Group": "Dining", "Amount": -900.0, "Type": "Expense"},  # other month
        {"_id": "x5", "Date": datetime(2026, 1, 9), "Group": "", "Amount": -33.0, "Type": "Expense"},           # blank Group
    ])
    dbhelper.seed(budgets, [
        {"_id": "bud_a", "budgetId": "BUD001", "versionName": "Baseline", "month": "2026-01",
         "status": "saved", "_created_at": datetime(2026, 1, 1, tzinfo=UTC)}])
    dbhelper.seed(budget_lines, [
        {"budget": "bud_a", "position": 0, "group": "Food", "amount": 1200},
        {"budget": "bud_a", "position": 1, "group": "Rent", "amount": 2100},
        {"budget": "bud_a", "position": 2, "group": "Gifts", "amount": 0},
    ])


def _rows():
    return {r["group"]: r for r in engine.build_report(engine.load_budget("bud_a"))}


def test_union_rows_and_match_values(store_db):
    _seed()
    by = _rows()
    assert set(by) == {"Food", "Rent", "Gifts", "Dining", "Salary"}   # union; blank Group excluded
    assert by["Food"]["match"] == "both"
    assert by["Rent"]["match"] == "budget_only"
    assert by["Dining"]["match"] == "actual_only" and by["Salary"]["match"] == "actual_only"
    # sorted by budget amount asc, actual-only rows last
    order = [r["group"] for r in engine.build_report(engine.load_budget("bud_a"))]
    assert order == ["Gifts", "Food", "Rent", "Dining", "Salary"]


def test_actual_only_expense_is_unbudgeted_and_unfavorable(store_db):
    _seed()
    d = (_rows())["Dining"]
    assert d["alert_level"] == "Unbudgeted" and d["favorable"] is False
    assert d["budget_amount"] == 0.0 and d["actual_amount"] == -210.0 and d["variance"] == -210.0
    assert d["variance_pct"] is None and d["score"] is None


def test_actual_only_income_is_favorable(store_db):
    _seed()
    s = (_rows())["Salary"]
    assert s["kind"] == "income" and s["alert_level"] == "Unbudgeted" and s["favorable"] is True


def test_budget_only_keeps_critical_under_and_zero_line_stays_on_target(store_db):
    _seed()
    by = _rows()
    assert by["Rent"]["alert_level"] == "Critical Under" and by["Rent"]["favorable"] is True
    assert by["Rent"]["actual_amount"] == 0.0 and by["Rent"]["score"] == 0
    assert by["Gifts"]["match"] == "budget_only" and by["Gifts"]["alert_level"] == "On Target"
    assert by["Food"]["alert_level"] == "High Over"                    # existing verdict maths unchanged


def test_page_totals_include_unbudgeted_and_show_counts(store_client):
    _seed()
    r = store_client.get("/budgets/bud_a/report")
    assert r.status_code == 200
    html = r.text
    # actual total = -1455 (Food) + 0 + 0 + -210 (Dining) + 8000 (Salary) = 6335
    assert "Actual <strong>$6,335.00</strong>" in html
    assert "Budget <strong>$3,300.00</strong>" in html
    assert "Unbudgeted <strong>2</strong>" in html and "No activity <strong>2</strong>" in html
    assert "On target <strong>1/5</strong>" in html                    # only the zero-amount line
    assert '"match": "actual_only"' in html                              # rows reach the grid
