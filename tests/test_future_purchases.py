"""The future-purchases Pull (app/future_purchases.py, ADR-0023 D5): conversion and the
group fallback chain, the per-field merge rule, and pull() end to end over a mocked
transport — create, update, hand edit survives, withdraw, re-decide, failures logged,
unconfigured → 503 — plus the sync route and the Activity page."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from app import expected_flows as flows
from app import future_purchases as fp
from app.store.categories import categories
from app.store.expected_flows import expected_flows
from app.store.sync_runs import sync_runs
from app.web import DomainError
from tests import dbhelper

TODAY = datetime(2026, 10, 5, tzinfo=UTC)
URL = "http://future-purchases:8000"


def export(purchases=(), recurring=()):
    return {"generated_at": "2026-10-05T20:00:00+00:00", "purchases": list(purchases), "recurring": list(recurring)}


LAPTOP = {"res_id": "RES-027", "item_name": "Field laptop", "category": "Computers", "group": "Equipment",
          "est_cost": 2400.0, "target_date": "2027-09-01", "status": "decided", "priority": "high",
          "edited_at": "2026-10-01T10:00:00+00:00"}
DESK = {"res_id": "RES-040", "item_name": "Standing desk", "category": "Office", "group": None,
        "est_cost": 520.0, "target_date": None, "status": "decided", "priority": "medium", "edited_at": None}
FILTERS = {"rec_id": "REC-003", "item_name": "Water filters", "category": "Kitchen", "group": "Household",
           "est_cost": 32.0, "interval": "Quarterly", "interval_days": 91, "last_restocked": "2026-08-20",
           "next_due": "2026-11-19", "edited_at": None}


def transport_for(payload, status=200, raw=None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/planned" and request.method == "GET"
        if raw is not None:
            return httpx.Response(status, content=raw)
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def _seed_groups():
    dbhelper.seed(categories, [
        {"_id": "Laptop", "Category": "Laptop", "Group": "Equipment", "Type": "Expense"},
        {"_id": "Cleaning", "Category": "Cleaning", "Group": "Household", "Type": "Expense"},
        {"_id": "Office", "Category": "Office", "Group": "Office", "Type": "Expense"},
    ])


def test_group_fallback_chain():
    groups = ["Equipment", "Office", "Household"]
    assert fp.group_for("Equipment", "Computers", groups) == "Equipment"      # the FP group names a ledger Group
    assert fp.group_for("equipment", "x", groups) == "Equipment"              # case folded, ledger spelling wins
    assert fp.group_for(None, "Office", groups) == "Office"                   # the category does
    assert fp.group_for("Gadgets", "Toys", groups) == "Planned"               # neither
    assert fp.group_for(None, None, []) == "Planned"


def test_to_flow_purchase_and_recurring():
    groups = ["Equipment", "Household"]
    lap = fp.to_flow(LAPTOP, groups)
    assert lap == {"doc_id": None, "external_id": "RES-027", "name": "Field laptop", "group": "Equipment", "amount": 2400.0,
                   "cadence": "once", "anchor_date": "2027-09-01", "priority": "high", "external_status": "decided"}
    assert fp.to_flow({**LAPTOP, "id": "abc"}, groups)["doc_id"] == "abc"
    desk = fp.to_flow(DESK, groups)
    assert desk["anchor_date"] is None and desk["group"] == "Planned"
    filt = fp.to_flow(FILTERS, groups)
    assert filt["cadence"] == "quarterly" and filt["anchor_date"] == "2026-11-19" and filt["external_status"] == "active"
    assert fp.to_flow({**FILTERS, "interval": "Semi-monthly"}, groups)["cadence"] == "biweekly"
    assert fp.to_flow({**FILTERS, "interval": "Bi-monthly"}, groups)["cadence"] == "bimonthly"
    assert fp.to_flow({**FILTERS, "interval": "Semi-annual"}, groups)["cadence"] == "semiyearly"
    assert fp.to_flow({**FILTERS, "interval": "Weekly-ish"}, groups)["cadence"] == "irregular"


def test_merge_overwrites_only_untouched_fields():
    snapshot = {"name": "Field laptop", "group": "Equipment", "amount": 2400.0, "cadence": "once",
                "anchor_date": "2027-09-01", "priority": "high"}
    current = {"name": "Field laptop", "group": "Computers", "amount": 2400.0, "cadence": "once",
               "anchor_date": "2027-06-01", "priority": "high", "pulled": snapshot}      # group + date hand-edited
    incoming = {**fp.to_flow(LAPTOP, ["Equipment"]), "amount": 2199.0, "anchor_date": "2027-10-01"}
    u = fp.merge(current, incoming)
    assert u["amount"] == 2199.0                       # untouched → follows the feed
    assert "group" not in u and "anchor_date" not in u   # hand-edited → kept
    assert u["pulled"]["amount"] == 2199.0 and u["external_status"] == "decided"
    # The feed dropping the date unplaces an untouched row through the placement rule.
    u2 = fp.merge({**current, "anchor_date": "2027-09-01"}, {**incoming, "anchor_date": None})
    assert u2.get("month", "x") is None and "anchor_date" not in u2
    # A row with no snapshot yet (first pull) takes everything.
    u3 = fp.merge({"name": "x", "amount": 1.0, "pulled": None}, incoming)
    assert u3["name"] == "Field laptop" and u3["amount"] == 2199.0


def test_pull_creates_updates_keeps_hand_edits_withdraws_and_reactivates(store_db):
    _seed_groups()
    r = fp.pull(TODAY, transport=transport_for(export([LAPTOP, DESK], [FILTERS])), base_url=URL)
    assert r["ok"] and r["status"] == "ok" and (r["created"], r["updated"], r["withdrawn"]) == (2, 0, 0)
    rows = {f["external_id"]: f for f in expected_flows.pulled()}
    assert "REC-003" not in rows                                            # recurring restocks are not pulled
    assert rows["RES-027"]["origin"] == "future-purchases" and rows["RES-027"]["group"] == "Equipment"
    assert rows["RES-027"]["anchor_date"].isoformat()[:10] == "2027-09-01" and rows["RES-027"]["day_known"] is True
    assert rows["RES-040"]["anchor_date"] is None and rows["RES-040"]["group"] == "Office"   # its category names a ledger Group
    [run] = sync_runs.recent("future-purchases")
    assert run["status"] == "ok" and run["txns_new"] == 2 and run["trigger"] == "manual" and run["finished_at"]
    # Hand edits: move the laptop to June and regroup it; the feed later changes its cost.
    flows.update_flow({"id": rows["RES-027"]["_id"], "month": "2027-06", "group": "Computers"})
    r = fp.pull(TODAY, transport=transport_for(export([{**LAPTOP, "est_cost": 2199.0}], [FILTERS])), base_url=URL)
    assert (r["created"], r["updated"], r["withdrawn"]) == (0, 1, 1)
    lap = expected_flows.by_external_id("RES-027")
    assert lap["amount"] == 2199.0                                           # untouched field follows the feed
    assert lap["anchor_date"].isoformat()[:10] == "2027-06-01" and lap["group"] == "Computers"   # hand edits survive
    desk = expected_flows.by_external_id("RES-040")
    assert desk["active"] is False and desk["external_status"] == "withdrawn"   # no longer decided
    # Re-decided: it comes back active by the same rule.
    r = fp.pull(TODAY, transport=transport_for(export([LAPTOP, DESK], [FILTERS])), base_url=URL)
    assert r["reactivated"] == 1 and (expected_flows.by_external_id("RES-040"))["active"] is True
    assert len(sync_runs.recent("future-purchases")) == 3
    # A cheap decided item is still pulled: there is no cost floor.
    r = fp.pull(TODAY, transport=transport_for(export([LAPTOP, DESK, {**DESK, "res_id": "RES-041", "item_name": "Registration sticker", "est_cost": 12.5}])), base_url=URL)
    assert r["created"] == 1 and (expected_flows.by_external_id("RES-041"))["amount"] == 12.5


def test_pull_failures_are_logged_and_write_nothing(store_db):
    def boom(request):
        raise httpx.ConnectError("refused")
    r = fp.pull(TODAY, transport=httpx.MockTransport(boom), base_url=URL)
    assert r["ok"] is False and r["status"] == "failed" and "unreachable" in r["error"]
    r = fp.pull(TODAY, transport=transport_for(None, status=500), base_url=URL)
    assert r["status"] == "failed" and "500" in r["error"]
    r = fp.pull(TODAY, transport=transport_for(None, raw=b"<html>"), base_url=URL)
    assert r["status"] == "failed" and "not JSON" in r["error"]
    r = fp.pull(TODAY, transport=transport_for({"purchases": "nope"}), base_url=URL)
    assert r["status"] == "failed"
    assert expected_flows.count() == 0
    runs = sync_runs.recent("future-purchases")
    assert len(runs) == 4 and all(x["status"] == "failed" and x["error"] for x in runs)
    # A free item is skipped and the run is partial, not failed.
    r = fp.pull(TODAY, transport=transport_for(export([{**DESK, "est_cost": 0}, LAPTOP])), base_url=URL)
    assert r["status"] == "partial" and r["created"] == 1
    assert (sync_runs.recent("future-purchases"))[0]["errlist"] == ["skipped RES-040: no cost"]


def test_pull_unconfigured_raises_503(store_db):
    with pytest.raises(DomainError) as e:
        fp.pull(TODAY, base_url="")
    assert e.value.status == 503


def test_sync_route_and_activity_page(store_client, monkeypatch):
    r = store_client.post("/api/planning/sync/future-purchases")
    assert r.status_code == 503 and r.json()["ok"] is False                 # unconfigured (conftest blanks env)
    r = store_client.post("/api/planning/sync/future-purchases?next=/planning/year", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/planning/year?sync=not-configured"
    html = (store_client.get("/activity")).text
    assert "<h2 class=\"health-h2\">future-purchases</h2>" in html and "FUTURE_PURCHASES_URL" in html
    # Configured through the module (the env is read at import): a mocked transport is not
    # reachable from the route, so patch pull itself to a stub and check the wiring.
    def fake_pull(trigger="manual"):
        import uuid
        sync_runs.insert({"_id": "run_" + uuid.uuid4().hex, "feed": "future-purchases", "started_at": datetime.now(UTC),
                                "finished_at": datetime.now(UTC), "status": "ok", "trigger": trigger,
                                "txns_new": 2, "txns_updated": 0})
        return {"ok": True, "run_id": "run_fake", "status": "ok", "created": 2, "updated": 0,
                "withdrawn": 0, "reactivated": 0, "error": None}
    monkeypatch.setattr(fp, "pull", fake_pull)
    monkeypatch.setattr("app.views.activity.FUTURE_PURCHASES_URL", URL)
    r = store_client.post("/api/planning/sync/future-purchases")
    assert r.json()["created"] == 2
    r = store_client.post("/api/planning/sync/future-purchases?next=/activity", follow_redirects=False)
    assert r.headers["location"] == "/activity?sync=ok"
    html = (store_client.get("/activity?sync=ok")).text
    assert "Pull future-purchases" in html and "2 new" in html
    assert "<td class=\"lbl\">future-purchases</td>" in html                 # the Feed column


def test_researching_items_arrive_with_their_status_and_sort_after_decided(store_db):
    _seed_groups()
    researching = {**DESK, "res_id": "RES-050", "item_name": "Camera", "status": "researching", "est_cost": 900.0}
    r = fp.pull(TODAY, transport=transport_for(export([DESK, researching])), base_url=URL)
    assert r["created"] == 2
    rows = {f["external_id"]: f for f in expected_flows.pulled()}
    assert rows["RES-050"]["external_status"] == "researching" and rows["RES-040"]["external_status"] == "decided"
    from app import planning
    shelf = (planning.year_plan(TODAY))["shelf"]
    assert [(s["name"], s["external_status"]) for s in shelf] == [("Standing desk", "decided"), ("Camera", "researching")]
