"""Cashflow rollup (app/rollup.py) — the single Income/Expense rule + the grouped
sum(Amount) helpers, with the year/month/start/end/where/like/nonblank/outflows scope in
place of the Mongo-era match dicts."""

from datetime import datetime

from app import rollup
from app.store.categories import categories
from app.store.transactions import transactions
from tests import dbhelper


def _seed():
    dbhelper.seed(transactions, [
        {"_id": "r1", "Date": datetime(2026, 3, 1), "Type": "Income", "Amount": 2000.0,
         "Group": "Salary", "Category": "Paycheck"},
        {"_id": "r2", "Date": datetime(2026, 3, 2), "Type": "Expense", "Amount": -500.0,
         "Group": "Food", "Category": "Groceries"},
        {"_id": "r3", "Date": datetime(2026, 3, 3), "Type": "Transfer", "Amount": 1000.0,
         "Group": "Xfer", "Category": "Move"},          # positive, but neither income nor expense
    ])


def test_income_expense_classifies_by_type_not_sign(store_db):
    _seed()
    income, expense = rollup.income_expense()
    assert income == 2000.0                              # the +1000 transfer is NOT income
    assert expense == 500.0                              # returned positive (abs)


def test_income_expense_respects_scope(store_db):
    _seed()
    assert rollup.income_expense(month="2026-03") == (2000.0, 500.0)
    assert rollup.income_expense(month="2026-04") == (0.0, 0.0)
    assert rollup.income_expense(year=2026, where={"Group": "Food"}) == (0.0, 500.0)


def test_totals_by_groups_sorted_most_negative_first(store_db):
    _seed()
    rows = rollup.totals_by("Group", month="2026-03")
    assert [r["name"] for r in rows] == ["Food", "Xfer", "Salary"]   # -500, 1000, 2000
    assert rows[0] == {"name": "Food", "total": -500.0}


def test_years_distinct_newest_first(store_db):
    dbhelper.seed(transactions, [
        {"_id": "y1", "Date": datetime(2024, 6, 1), "Amount": 1.0},
        {"_id": "y2", "Date": datetime(2026, 1, 2), "Amount": 1.0},
        {"_id": "y3", "Date": datetime(2026, 7, 3), "Amount": 1.0},   # same year, not double-counted
        {"_id": "y4", "Date": "not-a-date", "Amount": 1.0},           # non-date Date is skipped
        {"_id": "y5", "Amount": 1.0},                                 # no Date at all
    ])
    assert rollup.years() == [2026, 2024]


def test_totals_by_where_list_and_none_label(store_db):
    dbhelper.seed(transactions, [
        {"_id": "n1", "Date": datetime(2026, 9, 4), "Amount": -9.0, "Account": "Visa"},   # no Category
        {"_id": "n2", "Date": datetime(2026, 9, 5), "Amount": 5.0, "Category": "Misc",
         "Account": "Checking"},
    ])
    rows = rollup.totals_by("Category", where={"Account": ["Visa"]}, none_label="(uncat)")
    assert rows == [{"name": "(uncat)", "total": -9.0}]               # IN filter, blank → label
    assert rollup.totals_by("Category", where={"Category": None}) == [{"name": None, "total": -9.0}]


def test_totals_by_month_dimensions_and_counts(store_db):
    _seed()
    dbhelper.seed(transactions, [
        {"_id": "r4", "Date": datetime(2026, 4, 2), "Type": "Expense", "Amount": -50.0, "Group": "Food"}])
    rows = rollup.totals_by_month("Group")
    by_group = {(r["Group"], r["month"]): r for r in rows}
    assert by_group[("Salary", "2026-03")] == {"Group": "Salary", "month": "2026-03",
                                               "total": 2000.0, "count": 1}
    # One row per (Group, calendar month): the table's own `month` column must not swallow the grouping.
    assert by_group[("Food", "2026-03")]["total"] == -500.0
    assert by_group[("Food", "2026-04")]["total"] == -50.0
    assert [r["month"] for r in rows] == sorted(r["month"] for r in rows)


def test_totals_by_month_two_keys_year_and_nonblank(store_db):
    _seed()
    dbhelper.seed(transactions, [
        {"_id": "blank", "Date": datetime(2026, 3, 9), "Amount": -1.0, "Group": " "}])
    rows = rollup.totals_by_month(["Type", "Group"], year=2026)
    assert {(r["Type"], r["Group"], r["month"]) for r in rows} >= {
        ("Income", "Salary", "2026-03"), ("Expense", "Food", "2026-03")}
    assert rollup.totals_by_month("Group", year=1999) == []
    groups = {r["Group"] for r in rollup.totals_by_month("Group", nonblank=["Group"])}
    assert groups == {"Salary", "Food", "Xfer"}                      # the blank-Group row is out


def test_grand_total_sums_scope(store_db):
    _seed()
    assert rollup.grand_total(month="2026-03") == 2500.0    # 2000 - 500 + 1000
    assert rollup.grand_total(where={"Type": "Expense"}) == -500.0


def test_group_kinds_by_majority_category_type(store_db):
    dbhelper.seed(categories, dbhelper.SEED_CATEGORIES + [   # Auto/Food are Type "Spend"
        {"_id": "Paycheck", "Category": "Paycheck", "Group": "Salary", "Type": "Income"},
        {"_id": "Groceries", "Category": "Groceries", "Group": "Eats", "Type": "Expense"},
        {"_id": "Dining", "Category": "Dining", "Group": "Eats", "Type": "Expense"},
        {"_id": "Rebate", "Category": "Rebate", "Group": "Eats", "Type": "Income"},
    ])
    kinds = rollup.group_kinds()
    assert kinds["Salary"] == "income"
    assert kinds["Eats"] == "expense"                  # 2 Expense vs 1 Income
    assert "Transport" not in kinds                    # no Income/Expense categories


def test_scope_start_end_like_and_outflows(store_db):
    _seed()
    dbhelper.seed(transactions, [
        {"_id": "r4", "Date": datetime(2026, 3, 2, 18, 0), "Type": "Expense", "Amount": -25.0,
         "Group": "Food", "Category": "Groceries", "Description": "Corner SHOP"}])
    day2 = datetime(2026, 3, 2)
    assert rollup.grand_total(start=day2, end=datetime(2026, 3, 2, 23, 59, 59)) == -525.0
    assert rollup.grand_total(start=datetime(2026, 3, 3)) == 1000.0
    assert rollup.totals_by("Group", like={"Description": "shop"}) == [{"name": "Food", "total": -25.0}]
    assert rollup.totals_by("Group", outflows=True, month="2026-03") == [{"name": "Food", "total": -525.0}]
    assert rollup.grand_total(like={"Description": "100%"}) == 0.0          # LIKE wildcards escaped


def test_monthly_income_expense_and_date_span(store_db):
    _seed()
    dbhelper.seed(transactions, [
        {"_id": "r5", "Date": datetime(2026, 4, 9), "Type": "Expense", "Amount": 50.0, "Group": "Food"}])
    series = rollup.monthly_income_expense()
    assert series == [{"month": "2026-03", "income": 2000.0, "expense": 500.0, "net": 1500.0},
                      {"month": "2026-04", "income": 0.0, "expense": 50.0, "net": 50.0}]  # a refund is a negative expense
    lo, hi = rollup.date_span()
    assert (lo, hi) == (datetime(2026, 3, 1), datetime(2026, 4, 9))
    transactions.delete_where()
    assert rollup.date_span() == (None, None)
