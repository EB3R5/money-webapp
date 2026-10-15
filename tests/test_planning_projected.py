"""Projected P&L (app/planning.projected_pnl + /planning/projected, ADR-0023 slice 6): the
twelve columns (the first actual), one Planned row per Group with a placed item, the net row
matching the Year plan, the actual column's arithmetic, the flags, and the page."""

from app import planning, rollup
from tests.test_planning_year import TODAY, _seed_plan


def test_projected_pnl_columns_rows_and_net(store_db):
    _seed_plan()
    x = planning.projected_pnl(TODAY)
    plan = planning.year_plan(TODAY)
    assert x["columns"] == planning.plan_months(TODAY) and len(x["columns"]) == 12
    assert x["col_kind"]["2026-10"] == "actual" and x["col_kind"]["2026-11"] == "projected"
    assert x["labels"]["2026-10"] == "Oct 26" and x["labels"]["2027-01"] == "Jan 27"
    sections = {s["label"]: s for s in x["table"]["sections"]}
    assert list(sections) == ["Income", "Spend", "Planned", "Savings"]
    planned = {r["group"]: r for r in sections["Planned"]["rows"]}
    assert set(planned) == {"Car", "Pet"}                           # Equipment unplaced, Misc dated earlier
    assert planned["Car"]["by_col"]["2026-11"] == 700.0 and planned["Car"]["by_col"]["2027-01"] == 1200.0
    assert planned["Car"]["total"] == 1900.0 and planned["Pet"]["by_col"]["2027-03"] == 600.0
    assert sections["Planned"]["subtotals"]["2026-11"] == 700.0
    # Projected columns: the net equals the Year plan's month by month.
    for m in plan["months"][1:]:
        assert x["net"]["by_col"][m["month"]] == m["net"], m["month"]
    assert x["flags"] == [c for c in x["columns"] if x["net"]["by_col"][c] < 0]
    assert x["net"]["total"] == round(sum(x["net"]["by_col"].values()), 2)
    assert x["year_plan"]["start"] == "2026-10"


def test_projected_pnl_actual_column_reads_the_ledger(store_db):
    _seed_plan()
    x = planning.projected_pnl(TODAY)
    plan = planning.year_plan(TODAY)
    cur = plan["months"][0]
    income, expense = rollup.income_expense(month="2026-10")
    rows = {r["label"]: r for s in x["table"]["sections"] for r in s["rows"]}
    assert rows["Income sources"]["by_col"]["2026-10"] == round(income, 2) == 8000.0
    assert rows["Recurring bills"]["by_col"]["2026-10"] == cur["bills"]
    assert rows["Variable spend"]["by_col"]["2026-10"] == round(max(0.0, expense - cur["bills"]), 2)
    assert rows["Savings contribution"]["by_col"]["2026-10"] == round(income * plan["target_rate"], 2)
    expected_net = round(income - cur["bills"] - max(0.0, expense - cur["bills"]) - income * plan["target_rate"], 2)
    assert x["net"]["by_col"]["2026-10"] == expected_net
    # Projected columns read the Year plan's base figures.
    nov = plan["months"][1]
    assert rows["Income sources"]["by_col"]["2026-11"] == nov["income"]
    assert rows["Variable spend"]["by_col"]["2026-11"] == nov["variable"]


def test_projected_page_renders(store_client):
    from app import expected_flows as flows
    from app.budgets import current_month
    cur = current_month()
    flows.add_flow({"kind": "expense", "name": "Tires", "group": "Car", "amount": 700, "cadence": "once",
                          "month": planning.next_month(cur)})
    r = store_client.get("/planning/projected")
    assert r.status_code == 200
    html = r.text
    assert "<h1>Projected P&L ·" in html and 'id="projected"' in html
    assert html.count('class="num proj"') == 11 and html.count('class="num actual"') == 1
    assert 'data-group="Car"' in html and "Planned · Car" in html and "Net after savings" in html
    assert 'id="b-move" hidden' in html and 'id="plan-data"' in html
    assert 'href="/planning/projected"' in html                        # nav
