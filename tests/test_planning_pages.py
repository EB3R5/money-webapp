"""Planning section pages (app/views/planning.py): the redirects, the Month page's tiles
and Budget-vs-Actual table, the nav menu, and the 404 for a malformed month."""

from datetime import datetime

from app.budgets import current_month
from app.store.balance_history import balance_history
from tests import dbhelper
from tests.test_planning import seed_month


def test_planning_redirects_to_the_current_month(store_client):
    for path in ("/planning", "/planning/month"):
        r = store_client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/planning/month/{current_month()}"


def test_month_page_tiles_table_and_links(store_client):
    seed_month()
    dbhelper.seed(balance_history, [
        {"_id": "s1", "Date": datetime(2025, 12, 31), "Account": "Checking", "Class": "Asset", "Balance": 1000.0},
        {"_id": "s2", "Date": datetime(2026, 1, 31), "Account": "Checking", "Class": "Asset", "Balance": 1500.0},
    ])
    r = store_client.get("/planning/month/2026-01")
    assert r.status_code == 200
    html = r.text
    assert "<h1>January 2026</h1>" in html
    assert 'href="/planning/month/2025-12"' in html and 'href="/planning/month/2026-02"' in html
    assert "Budget “Baseline”" in html
    tiles = html.split('class="summary-cards planning-tiles"', 1)[1].split("</div>\n\n", 1)[0]
    assert "$8,000" in tiles                                       # income
    assert "$1,698" in tiles and "budget $3,300" in tiles and "$1,602 under" in tiles
    assert "+$6,302" in tiles                                      # net
    assert "79%" in tiles and "target 20%" in tiles                # net savings rate
    assert "$1,500" in tiles and "+$500" in tiles and "vs 2025-12" in tiles
    assert "Budget vs actual" in html and 'id="bva"' in html
    assert '<span class="pill warn">unbudgeted</span>' in html     # Dining
    assert '<span class="pill none">no activity</span>' in html    # Rent
    assert '<span class="pill over">high over</span>' in html      # Food, 21% over
    assert 'href="/budgets/bud_a"' in html
    assert "<summary>Planning</summary>" in html and 'href="/planning/notebook"' in html


def test_month_page_without_a_budget_or_snapshots(store_client):
    r = store_client.get("/planning/month/2024-07")
    assert r.status_code == 200
    assert "No budget" in r.text and "No budget version for July 2024" in r.text
    assert "no Snapshots yet" in r.text


def test_month_page_rejects_a_malformed_month(store_client):
    for bad in ("2026-13", "2026-1", "garbage"):
        r = store_client.get(f"/planning/month/{bad}")
        assert r.status_code == 404 and "No such month" in r.text


def test_entry_api_round_trip_and_panel(store_client):
    seed_month()
    r = store_client.post("/api/planning/entry/2026-01", json={"body": "Food ran over."})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["entry"]["body"] == "Food ran over." and d["entry"]["figures"]["income"] == 8000.0
    assert d["entry"]["frozen_at"].startswith("20")
    page = (store_client.get("/planning/month/2026-01")).text
    assert 'id="entry-body"' in page and "Food ran over." in page
    assert "entry written" in page and '"period": "2026-01"' in page
    r = store_client.post("/api/planning/entry/2026-01/refreeze")
    assert r.json()["ok"] and r.json()["entry"]["figures"]["period"] == "2026-01"
    r = store_client.post("/api/planning/entry/2026-01/delete")
    assert r.json() == {"ok": True, "period": "2026-01"}
    assert (store_client.post("/api/planning/entry/2026-01/delete")).status_code == 404
    assert (store_client.post("/api/planning/entry/nope", json={"body": "x"})).status_code == 400
    # A year period is accepted by the same API.
    r = store_client.post("/api/planning/entry/2025", json={"body": "Year."})
    assert r.json()["ok"] and r.json()["entry"]["figures"]["period"] == "2025"
    # The running year has no frozen figures and nothing to refreeze.
    r = store_client.post("/api/planning/entry/2026", json={"body": "This year."})
    assert r.json()["ok"] and r.json()["entry"]["figures"] is None and r.json()["entry"]["frozen_at"] is None
    assert store_client.post("/api/planning/entry/2026/refreeze").status_code == 409


def test_month_page_shows_live_preview_without_an_entry(store_client):
    seed_month()
    page = (store_client.get("/planning/month/2026-01")).text
    assert '"entry": null' in page and '"preview": {' in page and "Not saved yet" in page


def test_prompt_chips_show_only_unaddressed_prompts(store_client):
    seed_month()
    page = (store_client.get("/planning/month/2026-01")).text
    assert 'id="prompts-card"' in page and "Prompts from the data" in page
    assert 'data-prompt-id="unbudgeted:Dining">Dining spent $210 with no budget line.</button>' in page
    assert 'data-prompt-id="over:Food">Food ran 21% over: $1,455 vs $1,200.</button>' in page
    assert 'data-prompt-id="idle:Rent"' in page and 'data-prompt-id="uncategorized"' in page
    store_client.post("/api/planning/entry/2026-01", json={"body": "Dining spent $210 with no budget line. Fine."})
    page = (store_client.get("/planning/month/2026-01")).text
    assert 'data-prompt-id="unbudgeted:Dining"' not in page and 'data-prompt-id="over:Food"' in page
    assert "1 addressed" in page


def test_prompts_card_is_hidden_when_nothing_to_say(store_client):
    page = (store_client.get("/planning/month/2024-07")).text
    assert '<div class="card" id="prompts-card" hidden>' in page
