"""Notebook page (Planning slice 7, ADR-0021 D7): the document blocks and their markers,
the month rail, the sparkline, and the page in view, Write, year and error modes."""

from datetime import UTC, datetime

from app import planning
from app.budgets import current_month
from app.store.balance_history import balance_history
from tests import dbhelper
from tests.test_planning import seed_month

FIG = {"period": "2026-01", "income": 8000.0, "expense": 1698.0, "net": 6302.0, "savings_rate": 0.7878,
       "net_worth": 1500.0, "net_worth_delta": 500.0, "net_worth_as_of": "2026-01",
       "budget_version": "Baseline", "budget_total": 3300.0, "actual_total": 1665.0,
       "misses": [{"group": "Food", "budget": 1200.0, "actual": 1455.0, "over": 255.0}],
       "months12": [f"2025-{m:02d}" for m in range(2, 13)] + ["2026-01"],
       "net12": [0.0] * 11 + [6302.0]}


def test_notebook_blocks_follow_the_markers():
    body = "Intro **bold**.\n\n  [[figures]]  \n\nMore.\n[[misses]]\nTail."
    blocks = planning.notebook_blocks(body, FIG)
    assert [k for k, _ in blocks] == ["html", "figures", "html", "misses", "html"]
    assert "<strong>bold</strong>" in blocks[0][1] and blocks[1][1] is FIG
    assert blocks[3][1] == FIG["misses"] and "Tail." in blocks[4][1]


def test_notebook_blocks_without_markers_put_figures_first_and_misses_last():
    blocks = planning.notebook_blocks("Just prose.", FIG)
    assert [k for k, _ in blocks] == ["figures", "html", "misses"]
    # a year's figures (no budget) get no misses block; an empty body is just the blocks
    year_fig = {**FIG, "budget_version": None, "misses": []}
    assert [k for k, _ in planning.notebook_blocks("Prose.", year_fig)] == ["figures", "html"]
    assert [k for k, _ in planning.notebook_blocks("", FIG)] == ["figures", "misses"]
    assert [k for k, _ in planning.notebook_blocks("[[misses]]", FIG)] == ["figures", "misses"]


def test_notebook_blocks_render_sanitised_markdown():
    blocks = planning.notebook_blocks("Hi <script>alert(1)</script> there", FIG)
    html = [d for k, d in blocks if k == "html"][0]
    assert "<script>" not in html and "there" in html


def test_sparkline_geometry():
    sp = planning.sparkline([0.0, 10.0, -10.0, 5.0], w=100, h=40)
    assert sp["w"] == 100 and sp["h"] == 40
    assert sp["line"].startswith("M4.0,") and sp["area"].endswith("Z")
    assert 4 < sp["zero_y"] < 36 and sp["last_x"] == 96.0
    assert planning.sparkline([])["line"].startswith("M")          # empty series still draws


def test_notebook_rail_months_years_and_written_markers(store_db):
    seed_month()
    planning.save_entry("2026-01", "x")
    planning.save_entry("2025", "the year")
    rail = planning.notebook_rail("2026-01", today=datetime(2026, 3, 15, tzinfo=UTC))
    months = [m for g in rail["groups"] for m in g["months"]]
    assert len(months) == 24 and months[0]["month"] == "2026-03" and months[-1]["month"] == "2024-04"
    by = {m["month"]: m for m in months}
    assert by["2026-01"]["written"] and by["2026-01"]["current"] and by["2026-01"]["net"] == 6302.0
    assert by["2026-02"]["net"] == -900.0 and not by["2026-02"]["written"]
    assert by["2026-01"]["label"] == "Jan"
    years = {g["year"]: g for g in rail["groups"]}
    assert set(years) == {"2026", "2025", "2024"}                 # rail years ∪ ledger years ∪ this year
    assert years["2025"]["written"] and not years["2026"]["written"]
    assert rail["max_net"] == 6302.0


def test_notebook_view_frozen_vs_live(store_db):
    seed_month()
    live = planning.notebook_view("2026-01", today=datetime(2026, 2, 10, tzinfo=UTC))
    assert live["frozen"] is False and live["entry"] is None and live["figures"]["income"] == 8000.0
    assert live["title"] == "January 2026" and live["prev"] == "2025-12" and live["next"] == "2026-02"
    assert {p["id"] for p in live["open_prompts"]} >= {"over:Food", "unbudgeted:Dining"}
    planning.save_entry("2026-01", "Food ran 21% over: $1,455 vs $1,200.", today=datetime(2026, 2, 1, tzinfo=UTC))
    v = planning.notebook_view("2026-01", today=datetime(2026, 2, 10, tzinfo=UTC))
    assert v["frozen"] is True and v["figures"]["frozen_at"].startswith("2026-02-01")
    assert "over:Food" not in {p["id"] for p in v["open_prompts"]} and v["addressed_count"] == 1
    y = planning.notebook_view("2026", today=datetime(2026, 12, 1, tzinfo=UTC))
    assert y["kind"] == "year" and y["title"] == "2026 in review" and y["prev"] == "2025" and y["next"] == "2027"
    assert y["open_prompts"] == [] and [k for k, _ in y["blocks"]] == ["figures"]


def test_notebook_redirects_to_the_current_month(store_client):
    r = store_client.get("/planning/notebook", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/planning/notebook/{current_month()}"


def test_notebook_month_page_view_mode(store_client):
    seed_month()
    dbhelper.seed(balance_history, [
        {"_id": "s1", "Date": datetime(2025, 12, 31), "Account": "Checking", "Class": "Asset", "Balance": 1000.0},
        {"_id": "s2", "Date": datetime(2026, 1, 31), "Account": "Checking", "Class": "Asset", "Balance": 1500.0},
    ])
    page = (store_client.get("/planning/notebook/2026-01")).text
    assert "<h1>January 2026</h1>" in page
    assert "No entry yet" in page and "figures live" in page and "live · frozen on first save" in page
    assert 'data-block="figures"' in page and 'data-block="misses"' in page
    assert "<span>Food</span><span>$1,455 of $1,200</span>" in page           # a miss row
    assert '<svg class="spark"' in page
    assert 'data-prompt-id="unbudgeted:Dining">Dining spent $210 with no budget line.</button>' in page
    assert 'href="/planning/notebook/2025-12"' in page and 'href="/planning/notebook/2026-02"' in page
    assert 'href="/planning/notebook/2026-01?edit=1"' in page and 'href="/planning/month/2026-01"' in page
    assert 'data-month="2026-01"' in page and "Year review" in page
    assert "<summary>Planning</summary>" in page
    # with an entry: written byline, frozen figures, rendered prose, addressed count
    store_client.post("/api/planning/entry/2026-01", json={"body": "Dining spent $210 with no budget line.\n\n[[misses]]\n\nMore *notes*."})
    page = (store_client.get("/planning/notebook/2026-01")).text
    assert "Written 20" in page and "Figures frozen at writing" in page
    assert "<em>notes</em>" in page and "1 addressed" in page
    assert 'data-prompt-id="unbudgeted:Dining"' not in page
    assert page.index('data-block="figures"') < page.index("<em>notes</em>") < page.index('data-block="misses"') or \
        page.index('data-block="misses"') < page.index("<em>notes</em>")


def test_notebook_write_mode_year_page_and_404(store_client):
    seed_month()
    page = (store_client.get("/planning/notebook/2026-01?edit=1")).text
    assert 'id="nb-body"' in page and 'id="nb-preview"' in page and 'id="nb-save"' in page
    assert 'href="/planning/notebook/2026-01">Done</a>' in page
    year = (store_client.get("/planning/notebook/2026")).text
    assert "<h1>2026 in review</h1>" in year and 'data-block="figures"' in year
    assert 'data-block="misses"' not in year and "Not yet addressed" not in year
    assert 'href="/planning/notebook/2025"' in year and 'href="/planning/notebook/2027"' in year
    for bad in ("2026-13", "26", "garbage"):
        r = store_client.get(f"/planning/notebook/{bad}")
        assert r.status_code == 404 and "No such month or year" in r.text
