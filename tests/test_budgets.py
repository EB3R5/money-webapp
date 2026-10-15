"""Budget versions on the store layer: the list/editor/report pages, a draft seeded from
trailing history, save, delete-with-audit, and the per-line edits (app/views/budgets.py
+ app/budgets.py over the budgets and budget_lines stores)."""

from datetime import datetime

from app import budgets as engine
from app.store.budget_lines import budget_lines
from app.store.budgets import budgets
from app.store.deletions import deletions
from app.store.transactions import transactions
from tests import dbhelper
from tests.test_budget_pivot import seed_budgets


def test_pages_render(store_client):
    seed_budgets()
    r = store_client.get("/budgets")
    assert r.status_code == 200 and "Baseline" in r.text and "Tight" in r.text
    r = store_client.get("/budgets/bud_a")
    assert r.status_code == 200 and '"group": "Salary"' in r.text and "BUD001" in r.text
    r = store_client.get("/budgets/bud_a/report")
    assert r.status_code == 200 and "Food" in r.text
    r = store_client.get("/budgets/nope", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/budgets"


def test_list_versions_counts_lines_and_totals_newest_first(store_db):
    seed_budgets()
    versions = engine.list_versions()
    assert [v["id"] for v in versions] == ["bud_b", "bud_a"]
    assert versions[1] == {"id": "bud_a", "budgetId": "BUD001", "versionName": "Baseline",
                           "month": "2026-01", "status": "saved", "groups": 3,
                           "total": 11300.0, "created": "2026-01-01"}


def test_new_draft_seeded_from_trailing_history(store_client):
    """Groups with activity inside the lookback get a line from their trailing average
    (>= 2 data points) and rank by spend; a group with one month is manual at 0."""
    now = datetime.now()
    y, m = now.year, now.month
    prev = datetime(y if m > 1 else y - 1, m - 1 if m > 1 else 12, 15)
    dbhelper.seed(transactions, [
        {"_id": "h1", "Date": datetime(y, m, 1), "Group": "Food", "Amount": -400.0},
        {"_id": "h2", "Date": prev, "Group": "Food", "Amount": -200.0},
        {"_id": "h3", "Date": datetime(y, m, 2), "Group": "Fun", "Amount": -50.0},
        {"_id": "old", "Date": datetime(2000, 1, 1), "Group": "Ancient", "Amount": -999.0},
    ])
    r = store_client.post("/budgets/api/new", json={"month": f"{y:04d}-{m:02d}",
                                                          "versionName": "  "})
    body = r.json()
    assert body["ok"]
    doc = engine.load_budget(body["id"])
    assert doc["budgetId"] == "BUD001" and doc["versionName"] == "Baseline" and doc["status"] == "draft"
    assert [l["group"] for l in doc["lines"]] == ["Food", "Fun"]     # by spend desc; Ancient outside lookback
    assert doc["lines"][0] == {"group": "Food", "amount": -300.0, "source": "historical", "dataPoints": 2}
    assert doc["lines"][1] == {"group": "Fun", "amount": 0.0, "source": "manual", "dataPoints": 1}
    # a second draft gets the next id
    r2 = store_client.post("/budgets/api/new", json={"month": "2026-06", "versionName": "B"})
    assert (budgets.get(r2.json()["id"]))["budgetId"] == "BUD002"
    assert (store_client.post("/budgets/api/new", json={"month": "June"})).status_code == 400


def test_save_marks_version(store_client):
    seed_budgets()
    budgets.update("bud_a", {"status": "draft"})
    assert (store_client.post("/budgets/api/bud_a/save")).json() == {"ok": True}
    assert (budgets.get("bud_a"))["status"] == "saved"
    assert (store_client.post("/budgets/api/nope/save")).json() == {"ok": False}


def test_delete_audits_with_lines_then_cascades(store_client):
    seed_budgets()
    assert (store_client.post("/budgets/api/bud_a/delete")).json() == {"ok": True}
    assert budgets.get("bud_a") is None
    assert budget_lines.count({"budget": "bud_a"}) == 0        # lines cascade with the version
    assert budget_lines.count({"budget": "bud_b"}) == 3
    audit = dbhelper.one(deletions, collection="budgets")
    assert audit["doc"]["_id"] == "bud_a" and [l["group"] for l in audit["doc"]["lines"]] == ["Salary", "Food", "Rent"]
    assert (store_client.post("/budgets/api/bud_a/delete")).json() == {"ok": False}


def test_line_update_add_delete(store_client):
    seed_budgets()
    base = "/budgets/api/bud_a/line"
    r = store_client.post(base + "/update", json={"group": "Food", "amount": "$1,300"})
    assert r.json() == {"ok": True, "amount": 1300.0}
    line = budget_lines.one({"budget": "bud_a", "group": "Food"})
    assert line["amount"] == 1300.0 and line["source"] == "manual"
    assert (budgets.get("bud_a"))["_edited_at"] is not None
    assert (store_client.post(base + "/update", json={"group": "Nope", "amount": 1})).json()["ok"] is False
    assert (store_client.post(base + "/update", json={"group": "Food", "amount": "abc"})).status_code == 400
    assert (store_client.post(base + "/update", json={"amount": 1})).status_code == 400

    r = store_client.post(base + "/add", json={"group": "Fun", "amount": "—"})
    assert r.json() == {"ok": True, "line": {"group": "Fun", "amount": 0.0, "source": "manual", "dataPoints": 0}}
    assert [l["group"] for l in budget_lines.for_budget("bud_a")] == ["Salary", "Food", "Rent", "Fun"]
    assert (store_client.post(base + "/add", json={"group": "Fun", "amount": 5})).status_code == 409
    assert (store_client.post("/budgets/api/nope/line/add", json={"group": "X", "amount": 5})).json()["ok"] is False

    r = store_client.post(base + "/delete", json={"groups": ["Fun", "Rent"]})
    assert r.json() == {"ok": True}
    assert [l["group"] for l in budget_lines.for_budget("bud_a")] == ["Salary", "Food"]
    assert budget_lines.count({"budget": "bud_b"}) == 3         # other versions untouched
    assert (store_client.post(base + "/delete", json={"groups": []})).status_code == 400


def test_report_rows_and_summary(store_client):
    seed_budgets()
    rows = engine.build_report(engine.load_budget("bud_a"))
    by = {r["group"]: r for r in rows}
    assert by["Food"]["actual_amount"] == -1455.0 and by["Food"]["alert_level"] == "High Over"
    assert by["Salary"]["kind"] == "income" and by["Salary"]["alert_level"] == "On Target"
    assert [r["group"] for r in rows] == ["Food", "Rent", "Salary"]  # budget amount asc
