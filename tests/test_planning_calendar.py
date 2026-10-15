"""Calendar page (/planning/calendar, ADR-0023 slice 7): twelve month cards from the same
year_plan() facts as the Year plan, the shelf, the funds panel's short flag, placing through
the API, and the nav link."""

from app import expected_flows as flows
from app import planning, savings
from app.budgets import current_month


def _seed_calendar():
    """A goal with a small contribution and one big earmarked item (so the fund is short), a
    placed item in next month, an unplaced future-purchases item."""
    cur = current_month()
    nxt = planning.next_month(cur)
    g = savings.add_goal({"name": "Car fund", "target_amount": 3000})
    savings.update_goal({"id": g["id"], "monthly_contribution": 10})
    flows.add_flow({"kind": "expense", "name": "Timing belt", "group": "Car", "amount": 9000, "cadence": "once",
                          "month": nxt, "goal_id": g["id"]})
    flows.add_flow({"kind": "expense", "name": "Vet", "group": "Pet", "amount": 600, "cadence": "once",
                          "month": planning.next_month(nxt)})
    flows.add_flow({"kind": "expense", "name": "Standing desk", "group": "Equipment", "amount": 520,
                          "cadence": "once", "origin": "future-purchases", "external_id": "RES-040"})
    return cur, nxt, g["id"]


def test_calendar_cards_shelf_funds_and_nav(store_client):
    cur, nxt, gid = _seed_calendar()
    html = (store_client.get("/planning/calendar")).text
    assert "<h1>" in html and "→" in html and 'id="wall"' in html
    assert html.count('class="wm ') == 12 and f'data-month="{cur}"' in html
    belt_card = html.split(f'data-month="{nxt}"', 1)[1].split('class="wm ', 1)[0]
    assert "Timing belt" in belt_card and "$9,000" in belt_card and 'data-unplace=' in belt_card
    assert "part-funded" in belt_card                                      # 10/mo cannot cover 9,000
    assert f'<div class="wm flag" data-month="{nxt}"' in html             # 9,000 sinks the month
    assert 'data-shelf=' in html and "RES-040" in html and "Standing desk" in html
    assert f'data-goal-id="{gid}"' in html and "Car fund" in html and "· short" in html
    assert "$9,000 earmarked this window" in html
    assert 'href="/planning/calendar"' in html                             # nav
    assert 'id="plan-data"' in html and "Sync future-purchases · not configured" in html
    assert 'href="/planning/year"' in html                                 # Add planned spend


def test_calendar_placing_through_the_api_moves_an_item_into_its_card(store_client):
    cur, nxt, _ = _seed_calendar()
    desk = next(it for it in (planning.year_plan())["shelf"] if it["name"] == "Standing desk")
    target = planning.next_month(planning.next_month(nxt))
    r = store_client.post("/api/planning/flows/update", json={"id": desk["id"], "month": target})
    assert r.json()["ok"]
    html = (store_client.get("/planning/calendar")).text
    card = html.split(f'data-month="{target}"', 1)[1].split('class="wm ', 1)[0]
    assert "Standing desk" in card and 'class="item fp"' in card
    assert 'data-shelf=' not in html and "Everything is placed." in html
    r = store_client.post("/api/planning/flows/update", json={"id": desk["id"], "month": None})
    assert r.json()["ok"]
    html = (store_client.get("/planning/calendar")).text
    assert f'data-shelf="{desk["id"]}"' in html


def test_calendar_without_goals_points_at_the_savings_page(store_client):
    html = (store_client.get("/planning/calendar")).text
    assert "No savings goals yet" in html and 'href="/metrics"' in html
    assert "Everything is placed." in html
