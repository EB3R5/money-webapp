"""future-purchases Pull — planned spend read on demand from the sibling app (ADR-0023 D5).

Nothing here runs on a schedule. When the person presses the button, pull() reads
future-purchases' read-only planned export over the compose network, converts each decided
purchase to an expense flow of future-purchases origin, and upserts by the item's business
id. Only purchases: an open one-off (researching or decided) with a price and, usually, a
target date is what the money app cannot know by itself; its status rides along so the plan
can mark the undecided. Recurring restocks stay in future-purchases — they are
small, frequent, and already inside the variable spend rate, so pulling them would count
them twice (decided 2026-10-06, after the first real pull brought 34 of them in). There is
no cost floor: a cheap decided item, a registration say, is still a date to know about. Each pulled row keeps a `pulled` snapshot of what the
feed last said; merge() overwrites a field only when its current value still equals that
snapshot, so a hand edit survives every later pull (ADR-0019's rule in one column). An item
no longer in the export is deactivated with its status recorded, never deleted, and comes
back by the same rule. Every pull is a sync run with feed "future-purchases".
"""

import uuid
from datetime import UTC, date, datetime

import httpx

from . import budgets as engine
from . import expected_flows
from .config import FUTURE_PURCHASES_URL
from .store.expected_flows import expected_flows as flows_store
from .store.sync_runs import sync_runs
from .web import DomainError

FEED = "future-purchases"
EXPORT_PATH = "/api/planned"
FALLBACK_GROUP = "Planned"
INTERVAL_CADENCE = {"Semi-monthly": "biweekly", "Monthly": "monthly", "Bi-monthly": "bimonthly",
                    "Quarterly": "quarterly", "Semi-annual": "semiyearly", "Annual": "yearly"}
PULLED_FIELDS = ("name", "group", "amount", "cadence", "anchor_date", "priority")
SNAPSHOT_EXTRA = ("doc_id",)            # carried in the snapshot for reconciliation's flip to ordered


class FuturePurchasesError(DomainError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message, status=status)


# --- fetch ---------------------------------------------------------------------------------

def fetch_planned(base_url: str, *, transport: httpx.BaseTransport | None = None,
                  timeout: float = 10.0) -> dict:
    """GET the planned export; the transport is the test seam. Raises FuturePurchasesError
    on a network error, a non-200, a non-JSON body or a body without the two lists."""
    try:
        with httpx.Client(base_url=base_url, timeout=timeout, transport=transport) as client:
            r = client.get(EXPORT_PATH)
    except httpx.HTTPError as e:
        raise FuturePurchasesError(f"future-purchases unreachable: {type(e).__name__}")
    if r.status_code != 200:
        raise FuturePurchasesError(f"future-purchases answered {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise FuturePurchasesError("future-purchases answered with something that is not JSON")
    if not isinstance(data, dict) or not isinstance(data.get("purchases"), list) \
            or not isinstance(data.get("recurring"), list):
        raise FuturePurchasesError("future-purchases export is missing its lists")
    return data


# --- conversion (pure) ---------------------------------------------------------------------

def group_for(fp_group, fp_category, ledger_groups) -> str:
    """The item's Group: the future-purchases category's Group when it names a ledger Group,
    else the Category when it does, else FALLBACK_GROUP. Matched without case; the ledger's
    spelling wins."""
    by_lower = {g.lower(): g for g in ledger_groups if g}
    for candidate in (fp_group, fp_category):
        c = (candidate or "").strip().lower()
        if c and c in by_lower:
            return by_lower[c]
    return FALLBACK_GROUP


def _iso_day(v) -> str | None:
    if not v:
        return None
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    return str(v)[:10]


def to_flow(item: dict, ledger_groups) -> dict:
    """A planned-export row (purchase or recurring) as the fields of an expense flow."""
    if item.get("res_id"):
        return {
            "doc_id": item.get("id") or None,
            "external_id": item["res_id"], "name": (item.get("item_name") or item["res_id"]).strip(),
            "group": group_for(item.get("group"), item.get("category"), ledger_groups),
            "amount": round(float(item.get("est_cost") or 0), 2), "cadence": "once",
            "anchor_date": _iso_day(item.get("target_date")),
            "priority": (item.get("priority") or None), "external_status": item.get("status") or "decided",
        }
    return {
        "external_id": item["rec_id"], "name": (item.get("item_name") or item["rec_id"]).strip(),
        "group": group_for(item.get("group"), item.get("category"), ledger_groups),
        "amount": round(float(item.get("est_cost") or 0), 2),
        "cadence": INTERVAL_CADENCE.get(item.get("interval") or "", "irregular"),
        "anchor_date": _iso_day(item.get("next_due")),
        "priority": None, "external_status": item.get("state") or "active",
    }


def _norm(field: str, v):
    if field == "anchor_date":
        return _iso_day(v)
    if field == "amount":
        return round(float(v or 0), 2)
    return (v or None) if not isinstance(v, str) else (v.strip() or None)


def merge(current: dict, incoming: dict) -> dict:
    """The updates to apply to a pulled row: a field changes only when its current value
    still equals the last snapshot (the person has not touched it) and the feed now says
    something else. Always refreshes the snapshot and the external status."""
    snapshot = current.get("pulled") or {}
    updates: dict = {}
    for f in PULLED_FIELDS:
        now, was, new = _norm(f, current.get(f)), _norm(f, snapshot.get(f)), _norm(f, incoming.get(f))
        untouched = now == was or f not in snapshot
        if untouched and now != new:
            updates[f] = new
    if updates.get("anchor_date", "keep") is None and "anchor_date" in updates:
        updates["month"] = None                    # unplace through the placement rule
        del updates["anchor_date"]
    updates["pulled"] = {f: _norm(f, incoming.get(f)) for f in PULLED_FIELDS}
    updates["pulled"].update({f: incoming.get(f) for f in SNAPSHOT_EXTRA if incoming.get(f)})
    updates["external_status"] = incoming.get("external_status")
    return updates


# --- the pull ------------------------------------------------------------------------------

def _now():
    return datetime.now(UTC)


def pull(today: datetime | None = None, *, transport: httpx.BaseTransport | None = None,
               trigger: str = "manual", base_url: str | None = None) -> dict:
    """Run one pull and log it. Returns {ok, run_id, status, created, updated, withdrawn,
    reactivated, error}. Raises DomainError(503) when no URL is configured."""
    url = (base_url or FUTURE_PURCHASES_URL or "").rstrip("/")
    if not url:
        raise DomainError("future-purchases is not configured (FUTURE_PURCHASES_URL)", status=503)
    run_id = "run_" + uuid.uuid4().hex
    sync_runs.insert({"_id": run_id, "feed": FEED, "started_at": _now(), "status": "running",
                            "trigger": trigger, "chunks": 1, "requests_used": 0})
    counts = {"created": 0, "updated": 0, "withdrawn": 0, "reactivated": 0}
    status, error, errlist = "ok", None, []
    try:
        data = fetch_planned(url, transport=transport)
        sync_runs.update(run_id, {"requests_used": 1})
        ledger_groups = engine.all_groups()
        existing = {r["external_id"]: r for r in flows_store.pulled() if r.get("external_id")}
        seen: set[str] = set()
        for item in list(data["purchases"]):                   # purchases only; see the module docstring
            try:
                inc = to_flow(item, ledger_groups)
            except (KeyError, TypeError, ValueError) as e:
                errlist.append(f"skipped {item.get('res_id') or item.get('rec_id') or '?'}: {type(e).__name__}")
                continue
            if inc["amount"] <= 0:
                errlist.append(f"skipped {inc['external_id']}: no cost")
                continue
            seen.add(inc["external_id"])
            cur = existing.get(inc["external_id"])
            if cur is None:
                snapshot = {f: _norm(f, inc.get(f)) for f in PULLED_FIELDS}
                snapshot.update({f: inc.get(f) for f in SNAPSHOT_EXTRA if inc.get(f)})
                expected_flows.add_flow({**inc, "kind": "expense", "origin": expected_flows.PULLED,
                                               "pulled": snapshot})
                counts["created"] += 1
                continue
            updates = merge(cur, inc)
            if not cur.get("active", True):
                updates["active"] = True
                counts["reactivated"] += 1
            if any(k in updates for k in PULLED_FIELDS) or "month" in updates:
                counts["updated"] += 1
            expected_flows.update_flow({"id": cur["_id"], **updates})
        for ext, cur in existing.items():
            if ext not in seen and cur.get("active", True):
                expected_flows.update_flow({"id": cur["_id"], "active": False, "external_status": "withdrawn"})
                counts["withdrawn"] += 1
        if errlist:
            status = "partial"
    except DomainError as e:
        status, error = "failed", e.message
    except Exception as e:  # noqa: BLE001 — record it, never lose the run row
        status, error = "failed", f"{type(e).__name__}: {e}"
    finally:
        sync_runs.update(run_id, {"finished_at": _now(), "status": status,
                                        "txns_new": counts["created"], "txns_updated": counts["updated"],
                                        "txns_pending_dropped": counts["withdrawn"],
                                        "errlist": errlist, "error": error})
    return {"ok": status != "failed", "run_id": run_id, "status": status, **counts, "error": error}
