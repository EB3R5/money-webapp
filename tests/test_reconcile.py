"""Reconciliation (app/reconcile.py, #181) and the variable-rate net-out (#185): the match
rules, the pick order, the done link, the future-purchases flip, the API, the post-sync
hook, and that a matched row stops counting as variable spend."""

from datetime import UTC, date, datetime

import httpx

from app import expected_flows as flows
from app import planning, reconcile
from app.store.categories import categories
from app.store.expected_flows import expected_flows
from app.store.transactions import transactions
from tests import dbhelper

TODAY = datetime(2026, 10, 20, tzinfo=UTC)


def test_window_for_dated_and_month_only_placements():
    assert reconcile.window_for({"anchor_date": "2026-11-10", "day_known": True}) == (date(2026, 10, 27), date(2026, 11, 24))
    assert reconcile.window_for({"anchor_date": "2026-11-01", "day_known": False}) == (date(2026, 10, 18), date(2026, 12, 14))
    assert reconcile.window_for({"anchor_date": None}) is None


def test_pick_applies_group_window_tolerance_and_taken():
    flow = {"anchor_date": "2026-11-10", "day_known": True, "amount": 600.0, "group": "Pet"}
    groups_of = {"Veterinary": "Pet", "Groceries": "Food"}
    cands = [
        {"id": "a", "date": "2026-11-12", "amount": -612.0, "group": None, "category": "Veterinary"},   # via category's group
        {"id": "b", "date": "2026-11-09", "amount": -598.0, "group": "Pet", "category": None},         # closest amount
        {"id": "c", "date": "2026-11-09", "amount": -720.0, "group": "Pet", "category": None},         # 20% off
        {"id": "d", "date": "2026-12-20", "amount": -600.0, "group": "Pet", "category": None},         # outside the window
        {"id": "e", "date": "2026-11-10", "amount": -600.0, "group": "Food", "category": None},        # wrong group
        {"id": "f", "date": "2026-11-10", "amount": 600.0, "group": "Pet", "category": None},          # a refund, not an outflow
    ]
    assert reconcile.pick(flow, cands, groups_of, set())["id"] == "b"
    assert reconcile.pick(flow, cands, groups_of, {"b"})["id"] == "a"
    assert reconcile.pick(flow, cands, groups_of, {"a", "b"}) is None
    assert reconcile.pick({**flow, "anchor_date": None}, cands, groups_of, set()) is None


def _seed():
    dbhelper.seed(categories, [
        {"_id": "Veterinary", "Category": "Veterinary", "Group": "Pet", "Type": "Expense"},
        {"_id": "Groceries", "Category": "Groceries", "Group": "Food", "Type": "Expense"},
    ])
    dbhelper.seed(transactions, [
        {"_id": "t_vet", "Date": datetime(2026, 10, 14), "Category": "Veterinary", "Group": "Pet", "Amount": -585.0,
         "Type": "Expense", "Description": "SPRINGFIELD ANIMAL HOSPITAL"},
        {"_id": "t_food", "Date": datetime(2026, 10, 15), "Category": "Groceries", "Group": "Food", "Amount": -90.0, "Type": "Expense"},
        {"_id": "t_desk", "Date": datetime(2026, 10, 18), "Category": "Groceries", "Group": "Office", "Amount": -519.0, "Type": "Expense"},
    ])
    flows.add_flow({"kind": "expense", "name": "Vet", "group": "Pet", "amount": 600, "cadence": "once", "month": "2026-10"})
    flows.add_flow({"kind": "expense", "name": "Desk", "group": "Office", "amount": 520, "cadence": "once",
                          "anchor_date": "2026-10-20", "origin": "future-purchases", "external_id": "RES-040",
                          "pulled": {"doc_id": "fp-desk-id", "name": "Desk", "amount": 520.0}})
    flows.add_flow({"kind": "expense", "name": "Tires", "group": "Car", "amount": 700, "cadence": "once", "month": "2026-11"})


def test_reconcile_marks_matches_done_and_flips_pulled_items(store_db):
    _seed()
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.read()))
        return httpx.Response(200, json={"ok": True})
    r = reconcile.reconcile(TODAY, transport=httpx.MockTransport(handler), base_url="http://fp")
    assert r["checked"] == 3 and {m["name"] for m in r["matched"]} == {"Vet", "Desk"}
    vet = expected_flows.one({"name": "Vet"})
    assert vet["done_at"].isoformat()[:10] == "2026-10-14" and vet["done_txn"] == "t_vet"
    desk = expected_flows.one({"name": "Desk"})
    assert desk["done_txn"] == "t_desk"
    import json
    assert [(m, pth, json.loads(b)) for m, pth, b in calls] == [("POST", "/api/purchases/fp-desk-id", {"Status": "ordered"})]
    assert next(m for m in r["matched"] if m["name"] == "Desk")["flipped"] is True
    assert next(m for m in r["matched"] if m["name"] == "Vet")["flipped"] is False     # typed here, nothing to flip
    assert (expected_flows.one({"name": "Tires"}))["done_at"] is None               # nothing in its window
    # Done flows leave the plan; a second run finds nothing new and never re-links a taken row.
    assert [f["label"] for f in flows.planned_spend(TODAY)] == ["Tires"]
    assert (reconcile.reconcile(TODAY, base_url=""))["matched"] == []


def test_reconcile_without_pull_configured_still_marks_done(store_db):
    _seed()
    r = reconcile.reconcile(TODAY, base_url="")
    assert {m["name"] for m in r["matched"]} == {"Vet", "Desk"} and not any(m["flipped"] for m in r["matched"])


def test_variable_spend_nets_out_linked_rows(store_db):
    _seed()
    before = planning.variable_daily_spend(TODAY)
    reconcile.reconcile(TODAY, base_url="")
    after = planning.variable_daily_spend(TODAY)
    assert abs((before - after) * 90 - (585.0 + 519.0)) < 1.0                  # the two matched outflows (daily rate is rounded)
    assert reconcile.linked_outflow(date(2026, 10, 1), date(2026, 10, 31)) == 1104.0
    assert reconcile.linked_outflow(date(2026, 11, 1), date(2026, 11, 30)) == 0.0


def test_reconcile_route_and_sync_hook(store_client, monkeypatch):
    _seed()
    r = store_client.post("/api/planning/reconcile?next=/planning/year", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/planning/year?reconcile=2"
    html = (store_client.get("/planning/year?reconcile=2")).text
    assert "2 matched to the ledger" in html and ">Reconcile<" in html
    assert (store_client.post("/api/planning/reconcile")).json()["matched"] == []
    # The post-sync hook calls reconcile and never raises.
    from app.simplefin import sync as sfsync
    called = []
    def fake(today=None, **kw):
        called.append(1); raise RuntimeError("boom")
    monkeypatch.setattr(reconcile, "reconcile", fake)
    sfsync._reconcile_planned()
    assert called == [1]
