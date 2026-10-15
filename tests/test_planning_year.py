"""Year plan (app/planning.year_plan + /planning/year, ADR-0023 slice 4): the window, the
base net and flag arithmetic, funding coverage with earlier earmarks, the shelf and the
earlier strip, planned events in the forecast, the flow APIs and the page."""

from datetime import UTC, date, datetime

from app import expected_flows as flows
from app import planning, savings
from app.budgets import current_month
from app.store.accounts import accounts
from app.store.deletions import deletions
from app.store.expected_flows import expected_flows
from tests import dbhelper
from tests.test_planning_planner import _seed_year

TODAY = datetime(2026, 10, 5, tzinfo=UTC)


def test_plan_months_starts_with_the_current_month():
    months = planning.plan_months(TODAY)
    assert months[0] == "2026-10" and months[-1] == "2027-09" and len(months) == 12
    assert planning.plan_months(datetime(2026, 2, 1, tzinfo=UTC))[11] == "2027-01"


def test_base_month_arithmetic():
    income = [{"origin": "typed", "cadence": "monthly", "period_days": 30.44, "amount": 6840.0, "anchor_date": "2026-10-01"}]
    bills = [{"origin": "typed", "cadence": "monthly", "period_days": 30.44, "amount": 2900.0, "anchor_date": "2026-10-03"}]
    b = planning.base_month("2026-11", income, bills, 75.0, 0.2)
    assert b == {"month": "2026-11", "label": "November 2026", "income": 6840.0, "bills": 2900.0,
                 "variable": 2250.0, "savings": 1368.0, "base_net": 322.0}


def test_funding_coverage_with_earlier_earmarks():
    goal = {"id": "g1", "name": "Car fund", "current_balance": 720.0, "monthly_contribution": 150.0}
    first = planning.funding(700.0, goal, 0)                      # Nov: 720 + 150 = 870 available
    assert first == {"goal_id": "g1", "goal": "Car fund", "covered": 700.0, "pct": 1.0, "short": 0.0}
    later = planning.funding(1200.0, goal, 8, earlier_earmarked=700.0)   # Jul: 720 + 150×9 − 700 = 1370
    assert later["covered"] == 1200.0 and later["pct"] == 1.0
    tight = planning.funding(1200.0, goal, 2, earlier_earmarked=700.0)   # Jan: 720 + 450 − 700 = 470
    assert tight["covered"] == 470.0 and tight["pct"] == round(470 / 1200, 4) and tight["short"] == 730.0
    assert planning.funding(100.0, None, 0) is None


def _seed_plan():
    """The Planner seed (monthly Salary and Rent to 2026-10) plus a goal and four flows."""
    _seed_year(last="2026-10")
    g = savings.add_goal({"name": "Car fund", "target_amount": 3000})
    savings.update_goal({"id": g["id"], "monthly_contribution": 150})
    flows.add_flow({"kind": "expense", "name": "Tires", "group": "Car", "amount": 700, "cadence": "once",
                          "month": "2026-11", "goal_id": g["id"]})
    flows.add_flow({"kind": "expense", "name": "Timing belt", "group": "Car", "amount": 1200, "cadence": "once",
                          "anchor_date": "2027-01-20", "goal_id": g["id"]})
    flows.add_flow({"kind": "expense", "name": "Vet", "group": "Pet", "amount": 600, "cadence": "yearly",
                          "anchor_date": "2027-03-14"})
    flows.add_flow({"kind": "expense", "name": "Standing desk", "group": "Equipment", "amount": 520,
                          "cadence": "once", "origin": "future-purchases", "external_id": "RES-040"})
    flows.add_flow({"kind": "expense", "name": "Old thing", "group": "Misc", "amount": 50, "cadence": "once",
                          "month": "2026-08"})
    return g["id"]


def test_year_plan_months_items_funding_shelf_and_past(store_db):
    gid = _seed_plan()
    p = planning.year_plan(TODAY)
    assert p["start"] == "2026-10" and p["end"] == "2027-09" and len(p["months"]) == 12
    assert p["months"][0]["kind"] == "partial" and p["months"][1]["kind"] == "expected"
    nov, jan, mar = p["months"][1], p["months"][3], p["months"][5]
    assert [it["name"] for it in nov["items"]] == ["Tires"] and nov["planned"] == 700.0
    assert nov["net"] == round(nov["base_net"] - 700.0, 2) and nov["flag"] == (nov["net"] < 0)
    # Funding: Tires in Nov (index 1) sees 0 + 150×2 = 300 of 700; Timing belt in Jan (index 3)
    # sees 150×4 − 700 earmarked → 0 (the pooled balance is 0 with no savings in the seed).
    assert nov["items"][0]["funding"]["covered"] == 300.0 and nov["items"][0]["funding"]["short"] == 400.0
    assert jan["items"][0]["name"] == "Timing belt" and jan["items"][0]["funding"]["covered"] == 0.0
    assert mar["items"][0]["name"] == "Vet" and mar["items"][0]["day_known"] is True
    assert [it["name"] for it in p["shelf"]] == ["Standing desk"] and p["shelf"][0]["external_id"] == "RES-040"
    assert [it["name"] for it in p["past"]] == ["Old thing"]
    [fund] = p["funds"]
    assert fund["id"] == gid and fund["per"] == 150.0 and fund["earmarked"] == 1900.0
    assert fund["by_end"] == 1800.0 and fund["short"] is True
    assert "Car" in p["groups"] and "Pet" in p["groups"] and "Rent" in p["groups"]   # flows' groups + ledger groups
    assert p["totals"]["planned"] == 2500.0 and p["totals"]["unplaced"] == 1 and p["totals"]["past"] == 1
    assert p["last_pull"] is None and p["pull_configured"] is False


def test_forecast_includes_placed_planned_spend_on_its_day(store_db):
    _seed_plan()
    dbhelper.seed(accounts, [{"_id": "a1", "Account": "Checking", "Category": "Checking Account", "Amount": 5000.0}])
    f = planning.forecast(today=TODAY, days=120)
    planned = [(e["date"], e["label"], e["amount"]) for e in f["events"] if e.get("planned")]
    assert ("2026-11-01", "Tires", -700.0) in planned                  # month-only → the 1st
    assert ("2027-01-20", "Timing belt", -1200.0) in planned
    assert not any(e["label"] == "Standing desk" for e in f["events"])  # unplaced


def test_flow_apis_add_move_done_delete(store_client):
    r = store_client.post("/api/planning/flows", json={"name": "Dentist", "group": "Health", "amount": 900,
                                                             "cadence": "once", "month": "2027-02"})
    assert r.status_code == 200 and r.json()["ok"]
    fid = r.json()["id"]
    row = expected_flows.get(fid)
    assert row["kind"] == "expense" and row["anchor_date"].isoformat()[:10] == "2027-02-01" and row["day_known"] is False
    assert (store_client.post("/api/planning/flows", json={"name": "x", "amount": 1, "cadence": "once"})).status_code == 400   # no group
    r = store_client.post("/api/planning/flows/update", json={"id": fid, "month": "2027-04"})
    assert r.json()["ok"] and (expected_flows.get(fid))["anchor_date"].isoformat()[:10] == "2027-04-01"
    r = store_client.post("/api/planning/flows/update", json={"id": fid, "month": None})
    assert (expected_flows.get(fid))["anchor_date"] is None
    r = store_client.post(f"/api/planning/flows/{fid}/done")
    assert r.json()["ok"] and (expected_flows.get(fid))["done_at"] is not None
    assert (store_client.post(f"/api/planning/flows/missing/done")).status_code == 404
    r = store_client.post("/api/planning/flows/delete", json={"id": fid})
    assert r.json() == {"ok": True, "deleted": 1}
    assert len(deletions.list({"collection": "expected_flows"})) == 1
    y = (store_client.get("/api/planning/year")).json()
    assert y["start"] == current_month() and len(y["months"]) == 12


def test_year_page_renders_pins_shelf_and_form(store_client):
    cur = current_month()
    flows.add_flow({"kind": "expense", "name": "Vet", "group": "Pet", "amount": 600, "cadence": "once",
                          "month": planning.next_month(cur)})
    flows.add_flow({"kind": "expense", "name": "Laptop", "group": "Equipment", "amount": 2400, "cadence": "once",
                          "origin": "future-purchases", "external_id": "RES-027"})
    html = (store_client.get("/planning/year")).text
    assert "<h1>Year plan ·" in html and 'id="timeline"' in html and html.count('class="col') == 12
    assert ">Vet<b>$600</b>" in html.replace("\n", "") or "Vet<b>$600</b>" in html
    assert 'id="shelf"' in html and "RES-027" in html
    assert 'id="flow-form"' in html and '<option value="once" selected>' in html
    assert "Sync future-purchases · not configured" in html
    assert 'href="/planning/year"' in html                                   # nav
    assert 'id="plan-data"' in html and '"start": "' + cur + '"' in html


def test_pages_render_after_a_pull_and_with_a_dated_goal(store_client):
    """Regression: the first real pull left a sync run (datetimes) in `last_pull` and a goal
    carried a target date; the pages' JSON data block could not serialise either."""
    from app.store.sync_runs import sync_runs
    sync_runs.insert({"_id": "run_x", "feed": "future-purchases", "started_at": datetime.now(UTC),
                            "finished_at": datetime.now(UTC), "status": "ok", "trigger": "manual", "txns_new": 3})
    g = savings.add_goal({"name": "Trip", "target_amount": 3000, "target_date": "2027-06-30"})
    flows.add_flow({"kind": "expense", "name": "Flights", "group": "Travel", "amount": 850, "cadence": "once",
                          "month": planning.next_month(current_month()), "goal_id": g["id"]})
    for path in ("/planning/year", "/planning/calendar", "/planning/projected", "/api/planning/year"):
        r = store_client.get(path)
        assert r.status_code == 200, path
    assert "last pull" in (store_client.get("/planning/year")).text


# --- a movable window and the calendar's drag targets (#184) ---------------------------------

def test_plan_months_accepts_a_start_month():
    assert planning.plan_months(TODAY, "2027-01")[0] == "2027-01" and planning.plan_months(TODAY, "2027-01")[-1] == "2027-12"
    assert planning.plan_months(TODAY, "garbage")[0] == "2026-10"           # a bad start falls back to today
    assert planning.plan_months(TODAY, None)[0] == "2026-10"


def test_year_plan_with_a_moved_window(store_db):
    _seed_plan()
    p = planning.year_plan(TODAY, start="2026-08")
    assert p["start"] == "2026-08" and p["end"] == "2027-07" and p["current_month"] == "2026-10"
    assert [m["kind"] for m in p["months"][:3]] == ["past", "past", "partial"]
    assert p["window"] == {"earlier": "2026-07", "later": "2026-09", "moved": True}
    assert [it["name"] for it in p["past"]] == []                            # "Old thing" (2026-08) is inside the window now
    assert [it["name"] for m in p["months"] if m["month"] == "2026-08" for it in m["items"]] == ["Old thing"]
    home = planning.year_plan(TODAY)
    assert home["window"]["moved"] is False and home["window"]["earlier"] == "2026-09"


def test_pages_take_a_start_param_and_the_calendar_is_draggable(store_client):
    cur = current_month()
    later = planning.next_month(cur)
    flows.add_flow({"kind": "expense", "name": "Vet", "group": "Pet", "amount": 600, "cadence": "once", "month": later})
    flows.add_flow({"kind": "expense", "name": "Desk", "group": "Office", "amount": 500, "cadence": "once"})
    for path in ("/planning/year", "/planning/calendar", "/planning/projected"):
        html = (store_client.get(f"{path}?start={later}")).text
        assert f'href="?start={planning.prev_month(later)}"' in html and f'href="?start={planning.next_month(later)}"' in html
        assert f'href="{path}">today</a>' in html                            # moved → a way back
        assert "today</a>" not in (store_client.get(path)).text        # not moved → no link back
    assert (store_client.get("/api/planning/year?start=" + later)).json()["start"] == later
    assert (store_client.get("/api/planning/year?start=bad")).json()["start"] == cur
    html = (store_client.get("/planning/calendar")).text
    assert 'draggable="true"' in html and 'id="shelf-card"' in html and "drag onto a month" in html


def test_researching_pill_on_the_pages(store_client):
    cur = current_month()
    flows.add_flow({"kind": "expense", "name": "Camera", "group": "Equipment", "amount": 900, "cadence": "once",
                          "origin": "future-purchases", "external_id": "RES-050", "external_status": "researching",
                          "month": planning.next_month(cur)})
    for path in ("/planning/year", "/planning/calendar"):
        html = (store_client.get(path)).text
        assert 'class="pill none">researching</span>' in html, path
