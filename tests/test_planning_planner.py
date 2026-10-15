"""Planner page (app/planning.year_facts + /planning/planner/{year}, Planning slice 8): the
year strip's actual / partial / expected months, expected income per source for the year,
sinking funds from the savings goals, and the current month's journal drawer."""

from datetime import UTC, datetime

from app import planning
from app.budgets import current_month
from app.store.categories import categories
from app.store.savings_goals import savings_goals
from app.store.transactions import transactions
from tests import dbhelper
from tests.test_planning import seed_month

TODAY = datetime(2026, 3, 10, tzinfo=UTC)


def _months_back(ym: str, n: int) -> list[str]:
    """ym and the n-1 months before it, oldest first."""
    out = [ym]
    for _ in range(n - 1):
        out.insert(0, planning.prev_month(out[0]))
    return out


def _seed_year(last: str = "2026-03"):
    """seed_month's January plus a monthly Salary and a monthly Rent bill (Monthly-timed
    category) for the five months ending at `last`, and one non-recurring spend a month
    before `last` so the variable-spend window has something in it."""
    seed_month()
    categories.update("Rent", {"Timing": "Monthly"})
    rows = []
    for i, ym in enumerate(_months_back(last, 5)):
        y, m = int(ym[:4]), int(ym[5:7])
        rows.append({"_id": f"sal{i}", "Date": datetime(y, m, 1), "Group": "Salary", "Category": "Salary",
                     "Amount": 8000.0, "Type": "Income"})
        rows.append({"_id": f"rent{i}", "Date": datetime(y, m, 3), "Group": "Rent", "Category": "Rent",
                     "Description": "RENT PAYMENT", "Amount": -2100.0, "Type": "Expense"})
    pm = planning.prev_month(last)
    rows.append({"_id": "misc1", "Date": datetime(int(pm[:4]), int(pm[5:7]), 20), "Group": "Dining",
                 "Category": "Dining", "Amount": -900.0, "Type": "Expense"})
    dbhelper.seed(transactions, rows)


def test_year_facts_months_actual_partial_expected(store_db):
    _seed_year()
    y = planning.year_facts("2026", today=TODAY)
    kinds = [m["kind"] for m in y["months"]]
    assert kinds == ["actual", "actual", "partial"] + ["expected"] * 9
    jan, mar, apr = y["months"][0], y["months"][2], y["months"][3]
    assert jan["income"] == 16000.0 and jan["expense"] == 3798.0            # seed_month's 8000 + sal2; 1698 + rent
    assert mar["month"] == "2026-03" and mar["income"] == 8000.0 and mar["expense"] == 2100.0
    assert apr["income"] == 8000.0                                          # the monthly Salary series
    assert apr["expense"] == round(2100.0 + y["variable_daily"] * 30, 2)    # the Rent bill + variable spend
    assert y["variable_daily"] > 0 and y["variable_daily"] < 50             # 90-day spend net of rent, per day
    # Jan 1698 + 2100, Feb 900 (seed_month) + 900 + 2100, Mar 2100 → 9798 out against 32000 in
    assert y["totals"]["income_ytd"] == 32000.0 and y["totals"]["net_ytd"] == 22202.0
    assert y["is_current_year"] is True and y["current_month"] == "2026-03"
    assert y["prev"] == "2025" and y["next"] == "2027"


def test_year_facts_expected_income_and_funds(store_db):
    _seed_year()
    dbhelper.seed(savings_goals, [{"_id": "g1", "name": "Trip", "target_amount": 3000.0, "target_date": "2026-12-31"}])
    y = planning.year_facts("2026", today=TODAY)
    by = {s["source"]: s for s in y["expected_income"]}
    assert by["Salary"]["cadence"] == "monthly" and by["Salary"]["expected_year"] == 96000.0
    assert by["Salary"]["received_ytd"] == 32000.0 and by["Salary"]["remaining"] == 64000.0
    assert by["Salary"]["next"] == "2026-03-31"
    assert y["expected_total"] == 96000.0 and y["received_total"] == 32000.0 and y["remaining_total"] == 64000.0
    assert [g["name"] for g in y["funds"]] == ["Trip"]
    assert y["funds"][0]["target_amount"] == 3000.0 and y["funds"][0]["on_track"] in ("behind", "no_savings")


def test_year_facts_for_an_empty_year(store_db):
    y = planning.year_facts("2019", today=TODAY)
    assert all(m["kind"] == "actual" and m["net"] == 0.0 for m in y["months"])
    assert y["expected_income"] == [] and y["funds"] == [] and y["is_current_year"] is False


def test_planner_redirect_and_404(store_client):
    r = store_client.get("/planning/planner", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/planning/planner/{current_month()[:4]}"
    for bad in ("26", "garbage", "2026-01"):
        assert (store_client.get(f"/planning/planner/{bad}")).status_code == 404


def test_planner_page_strip_income_funds_and_drawer(store_client):
    # The page reads "today" from the clock, so the series must run up to the current month.
    cur = current_month()
    year = cur[:4]
    _seed_year(last=cur)
    dbhelper.seed(savings_goals, [{"_id": "g1", "name": "Trip", "target_amount": 3000.0}])
    html = (store_client.get(f"/planning/planner/{year}")).text
    assert f"<h1>{year}</h1>" in html and 'id="year-strip"' in html
    assert html.count('class="ym ') == 12
    assert f'data-month="{cur}" data-kind="partial"' in html
    assert 'data-kind="actual"' in html                                    # earlier months of the year
    assert 'id="expected-income"' in html and "estimated from ledger" in html
    assert 'data-source="Salary"' in html and "$96,000" in html            # 12 × 8000 expected for the year
    assert 'id="sinking-funds"' in html and 'data-goal-id="g1"' in html and "$3,000" in html
    assert f'Journal · {datetime.now(UTC).strftime("%b")}' in html
    assert f'"period": "{cur}"' in html and 'id="entry-body"' in html and 'id="drawer"' in html
    assert f'href="/planning/notebook/{year}"' in html and f'href="/planning/planner/{int(year) - 1}"' in html
    # The drawer saves the current month's entry through the shared API.
    r = store_client.post(f"/api/planning/entry/{cur}", json={"body": "From the drawer."})
    assert r.json()["ok"]
    html = (store_client.get(f"/planning/planner/{year}")).text
    assert "From the drawer." in html


def test_planner_page_without_goals_points_at_the_savings_page(store_client):
    html = (store_client.get("/planning/planner/2026")).text
    assert "No savings goals yet" in html and 'href="/metrics"' in html
