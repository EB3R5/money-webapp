"""Reconciliation — a planned spend meets its ledger transaction (#181, ADR-0023 follow-up).

A placed, not-yet-done planned spend is matched to one outflow in the ledger: same Group (or
a Category in that Group), dated within RECONCILE_DAYS of the anchor (a month-only placement
is matched anywhere in its month, with the same margin either side), with an amount within
RECONCILE_TOLERANCE of the plan, and not already linked to another planned spend. The best
candidate is the closest amount, then the closest date. A match marks the flow done on the
transaction's date and links the row; a flow pulled from future-purchases is also flipped
to ordered there, best effort, when the pull is configured. Runs on demand from the Year
plan and after each successful SimpleFIN sync. Nothing here moves money or edits the ledger.
"""

from datetime import UTC, date, datetime, timedelta

import httpx

from . import expected_flows
from .config import FUTURE_PURCHASES_URL
from .store.categories import categories
from .store.expected_flows import expected_flows as flows_store
from .store.transactions import transactions

RECONCILE_DAYS = 14
RECONCILE_TOLERANCE = 0.10


def _day(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def window_for(flow: dict) -> tuple[date, date] | None:
    """The dates a match may fall in: the anchor ± RECONCILE_DAYS, or for a month-only
    placement the whole month ± RECONCILE_DAYS."""
    anchor = _day(flow.get("anchor_date"))
    if anchor is None:
        return None
    margin = timedelta(days=RECONCILE_DAYS)
    if flow.get("day_known", True):
        return anchor - margin, anchor + margin
    first = anchor.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first - margin, nxt - timedelta(days=1) + margin


def pick(flow: dict, candidates: list[dict], groups_of: dict, taken: set[str]) -> dict | None:
    """The best transaction for a flow from `candidates` ({id, date, amount, group, category,
    description}): same Group (the row's Group, or its Category's Group), inside the window,
    amount within tolerance, not taken. Closest amount wins, then the closest date."""
    span = window_for(flow)
    if span is None or not flow.get("amount"):
        return None
    lo, hi = span
    anchor = _day(flow["anchor_date"])
    want = float(flow["amount"])
    best, best_key = None, None
    for t in candidates:
        if t["id"] in taken or not t.get("amount") or float(t["amount"]) >= 0:
            continue
        day = _day(t.get("date"))
        if day is None or not lo <= day <= hi:
            continue
        group = (t.get("group") or groups_of.get(t.get("category") or "") or "")
        if (flow.get("group") or "").strip().lower() != group.strip().lower():
            continue
        amt = abs(float(t["amount"]))
        if abs(amt - want) > want * RECONCILE_TOLERANCE:
            continue
        key = (abs(amt - want), abs((day - anchor).days))
        if best_key is None or key < best_key:
            best, best_key = t, key
    return best


def _candidates(lo: date, hi: date) -> list[dict]:
    rows = transactions.rows(
        'SELECT id, date, amount, "group", category, description FROM transactions '
        "WHERE amount < 0 AND (pending IS NULL OR pending != 1) AND substr(date, 1, 10) BETWEEN ? AND ?",
        [lo.isoformat(), hi.isoformat()])
    return [{"id": r[0], "date": r[1], "amount": r[2], "group": r[3], "category": r[4], "description": r[5]}
            for r in rows]


def _groups_of() -> dict:
    return {c["_id"]: c.get("Group") for c in categories.list() if c.get("_id")}


def flip_ordered(base_url: str, doc_id: str, *, transport=None, timeout: float = 10.0) -> bool:
    """Mark the future-purchases item ordered through its update route; False on any error."""
    try:
        with httpx.Client(base_url=base_url, timeout=timeout, transport=transport) as client:
            r = client.post(f"/api/purchases/{doc_id}", json={"Status": "ordered"})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def reconcile(today: datetime | None = None, *, transport=None, base_url: str | None = None) -> dict:
    """Match every placed, not-done planned spend; mark matches done; flip pulled ones to
    ordered. Returns {matched: [{flow_id, name, txn_id, date, amount, flipped}], checked}."""
    today = today or datetime.now(UTC)
    flows = [f for f in expected_flows.planned_spend(today) if f["placed"]]
    if not flows:
        return {"matched": [], "checked": 0}
    spans = [window_for(f) for f in flows]
    lo = min(s[0] for s in spans if s)
    hi = max(s[1] for s in spans if s)
    candidates = _candidates(lo, hi)
    groups_of = _groups_of()
    taken = {r["done_txn"] for r in flows_store.list() if r.get("done_txn")}
    url = (base_url or FUTURE_PURCHASES_URL or "").rstrip("/")
    matched = []
    for f in sorted(flows, key=lambda x: x["anchor_date"] or ""):
        t = pick(f, candidates, groups_of, taken)
        if t is None:
            continue
        taken.add(t["id"])
        day = _day(t["date"]).isoformat()
        expected_flows.update_flow({"id": f["id"], "done_at": day, "done_txn": t["id"]})
        flipped = False
        row = flows_store.get(f["id"])
        doc_id = ((row or {}).get("pulled") or {}).get("doc_id")
        if url and f["origin"] == expected_flows.PULLED and doc_id:
            flipped = flip_ordered(url, doc_id, transport=transport)
        matched.append({"flow_id": f["id"], "name": f["label"], "txn_id": t["id"], "date": day,
                        "amount": abs(float(t["amount"])), "description": t.get("description"),
                        "flipped": flipped})
    return {"matched": matched, "checked": len(flows)}


def linked_outflow(start: date, end: date) -> float:
    """Σ |amount| of transactions linked to done planned spend, dated in [start, end] —
    what the variable daily rate must not count twice (#185)."""
    ids = [r["done_txn"] for r in flows_store.list() if r.get("done_txn")]
    if not ids:
        return 0.0
    marks = ", ".join("?" for _ in ids)
    rows = transactions.rows(
        f"SELECT COALESCE(SUM(ABS(amount)), 0) FROM transactions WHERE id IN ({marks}) "
        "AND amount < 0 AND substr(date, 1, 10) BETWEEN ? AND ?",
        [*ids, start.isoformat(), end.isoformat()])
    return round(float(rows[0][0] or 0), 2)
