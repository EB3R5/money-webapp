"""Search on the planned-spend views (slice 3): the shared search.js mirror, the search box
and data-search tags on the Year plan, Calendar, Projected P&L and Income pages, and the
?q= prefill. The filtering itself is client-side (planning-search.js)."""

from pathlib import Path

from app import expected_flows as flows
from app import planning
from app.budgets import current_month
from app.store.categories import categories
from tests import dbhelper

STATIC = Path(__file__).resolve().parents[1] / "app" / "static" / "js"


def test_search_mirror_lives_in_one_file():
    search = (STATIC / "search.js").read_text()
    assert "window.searchTokens" in search and "window.searchHit" in search
    editor = (STATIC / "card-editor.js").read_text()
    assert "window.searchTokens =" not in editor and "search.js" in editor
    tpl = (Path(__file__).resolve().parents[1] / "app" / "templates" / "card_collection.html").read_text()
    assert tpl.index("js/search.js") < tpl.index("js/card-editor.js")


def test_pages_render_the_search_box_and_tagged_items(store_client):
    cur = current_month()
    dbhelper.seed(categories, [{"_id": "Salary", "Category": "Salary", "Group": "Work", "Type": "Income"}])
    flows.add_flow({"kind": "expense", "name": "Vet · annual", "group": "Pet", "amount": 600, "cadence": "once",
                          "month": planning.next_month(cur), "notes": "dental too"})
    flows.add_flow({"kind": "expense", "name": "Camera", "group": "Equipment", "amount": 900, "cadence": "once",
                          "origin": "future-purchases", "external_id": "RES-050", "external_status": "researching"})
    flows.add_source({"name": "Paycheck", "category": "Salary", "cadence": "monthly", "amount": 5000,
                            "anchor_date": f"{cur}-28"})
    for path in ("/planning/year", "/planning/calendar", "/planning/projected", "/planning/income"):
        html = (store_client.get(f"{path}?q=vet")).text
        assert 'id="plan-search"' in html and 'value="vet"' in html, path
        assert 'id="plan-no-match"' in html and "planning-search.js" in html and "js/search.js" in html, path
    year = (store_client.get("/planning/year")).text
    assert 'data-search="Vet · annual Pet  dental too"' in year
    assert 'data-search="Camera Equipment RES-050 "' in year                   # shelf chip
    cal = (store_client.get("/planning/calendar")).text
    assert cal.count('data-search="') >= 2
    proj = (store_client.get("/planning/projected")).text
    assert 'data-search="Pet Vet · annual"' in proj                             # the planned row: group + item names
    inc = (store_client.get("/planning/income")).text
    assert 'data-search="Paycheck Salary monthly "' in inc


def test_search_hides_survive_the_pages_display_rules_and_long_lists_scroll():
    """The Calendar's items and shelf entries set display: flex, which beats the UA [hidden]
    rule the search applies — the stylesheet must say [hidden] again for every searchable
    element. Long lists scroll instead of paginating."""
    css = (Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "app.css").read_text()
    assert ".wm .item[hidden], .shelf .item[hidden], .pin[hidden], .chip[hidden], tr[hidden] { display: none; }" in css
    assert ".scroll-list { max-height:" in css
    tpl = Path(__file__).resolve().parents[1] / "app" / "templates"
    assert 'class="shelf scroll-list"' in (tpl / "planning_calendar.html").read_text()
    assert 'class="chips scroll-list"' in (tpl / "planning_year.html").read_text()
    assert 'class="tablewrap scroll-list"' in (tpl / "planning_income.html").read_text()


def test_shelf_headings_count_the_items(store_client):
    for i in range(3):
        flows.add_flow({"kind": "expense", "name": f"Thing {i}", "group": "Misc", "amount": 10 + i, "cadence": "once"})
    assert "Not yet placed · 3 ·" in (store_client.get("/planning/year")).text
    assert "Not yet placed · 3 ·" in (store_client.get("/planning/calendar")).text
