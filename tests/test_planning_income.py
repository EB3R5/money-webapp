"""Income expected vs received (app/planning.income_table, Planning slice 6): the table
rows, totals and one-off rows, and the Month page card labelled as an estimate."""

from datetime import UTC, datetime

from app import planning
from app.store.categories import categories
from app.store.transactions import transactions
from tests import dbhelper
from tests.test_planning import seed_month


def _seed_income():
    seed_month()
    # Two earlier Salary months make it a monthly series; Dividends has no pattern.
    dbhelper.seed(transactions, [
        {"_id": "x6", "Date": datetime(2025, 11, 1), "Group": "Salary", "Category": "Salary", "Amount": 8000.0, "Type": "Income"},
        {"_id": "x7", "Date": datetime(2025, 12, 1), "Group": "Salary", "Category": "Salary", "Amount": 8000.0, "Type": "Income"},
        {"_id": "x8", "Date": datetime(2026, 1, 14), "Group": "Salary", "Category": "Dividends", "Amount": 42.0, "Type": "Income"},
    ])


def test_income_table_expected_received_and_one_off_rows(store_db):
    _seed_income()
    t = planning.income_table("2026-01", today=datetime(2026, 1, 20, tzinfo=UTC))
    by = {r["source"]: r for r in t["rows"]}
    assert by["Salary"]["cadence"] == "monthly" and by["Salary"]["expected"] == 8000.0
    assert by["Salary"]["received"] == 8000.0 and by["Salary"]["next"] == "2026-01-31"
    assert by["Dividends"] == {"source": "Dividends", "cadence": "one-off", "expected": None,
                               "received": 42.0, "next": None, "confidence": None, "origin": "one-off"}
    assert by["Salary"]["origin"] == "detected"
    assert t["expected_total"] == 8000.0 and t["received_total"] == 8042.0
    f = planning.month_facts("2026-01", today=datetime(2026, 1, 20, tzinfo=UTC))
    assert f["income_sources"]["received_total"] == 8042.0 and f["estimates"] == ["income_sources"]


def test_month_page_income_table_estimated_from_ledger(store_client):
    # The page reads "today" from the clock, and a series that stopped more than two
    # periods ago has ended, so the seed sits in the current and two prior months.
    from app.budgets import current_month
    cur = current_month()
    months = [planning.prev_month(planning.prev_month(cur)), planning.prev_month(cur), cur]
    dbhelper.seed(transactions, [
        {"_id": f"pay{i}", "Date": datetime.fromisoformat(f"{m}-01"), "Category": "Salary", "Amount": 8000.0, "Type": "Income"}
        for i, m in enumerate(months)
    ] + [{"_id": "div", "Date": datetime.fromisoformat(f"{cur}-01"), "Category": "Dividends", "Amount": 42.0, "Type": "Income"}])
    html = (store_client.get(f"/planning/month/{cur}")).text
    card = html.split('id="income-sources"', 1)[1]
    assert "estimated from ledger" in card
    assert '<tr data-source="Salary" data-cadence="monthly" data-origin="detected">' in card
    assert '<tr data-source="Dividends" data-cadence="one-off" data-origin="one-off">' in card
    assert "$8,000" in card and "$42" in card and "$8,042" in card   # expected, one-off received, received total
    assert "No recurring income found" not in card
    # A month with no income shows the empty state.
    empty = (store_client.get("/planning/month/2022-03")).text
    assert "No recurring income found in the last two years." in empty.split('id="income-sources"', 1)[1]


def test_once_income_counts_in_its_month_on_both_pages(store_db):
    """A one-off income (a tax refund, unclaimed property) has no period; it still expects
    its amount in the month of its date and nothing elsewhere, on the Month page's income
    table and in the Planner's expected income for the year."""
    from app import expected_flows as flows
    dbhelper.seed(categories, [{"_id": "Amplio", "Category": "Amplio", "Group": "Work", "Type": "Income"}])
    flows.add_source({"name": "Unclaimed property", "category": "Amplio", "cadence": "once", "amount": 1300,
                            "anchor_date": "2026-10-20"})
    today = datetime(2026, 10, 5, tzinfo=UTC)
    oct_rows = {r["source"]: r for r in (planning.income_table("2026-10", today))["rows"]}
    assert oct_rows["Unclaimed property"]["expected"] == 1300.0 and oct_rows["Unclaimed property"]["next"] == "2026-10-20"
    assert "Unclaimed property" not in {r["source"] for r in (planning.income_table("2026-11", today))["rows"]}
    y = planning.year_facts("2026", today=today)
    by = {s["source"]: s for s in y["expected_income"]}
    assert by["Unclaimed property"]["expected_year"] == 1300.0 and by["Unclaimed property"]["remaining"] == 1300.0
    assert next(m for m in y["months"] if m["month"] == "2026-10")["kind"] == "partial"
    assert next(m for m in y["months"] if m["month"] == "2026-11")["income"] == 0.0     # nothing expected after its month
