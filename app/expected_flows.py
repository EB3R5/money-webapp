"""Expected flows — typed money movements, income and planned spend (ADR-0022, ADR-0023).

One row per expected movement the ledger cannot detect: a kind (income or expense), a
cadence, an amount, the anchor date of its next occurrence (placed when it has one, unplaced
when it has none), a Category (income) or a ledger Group (expense), an optional savings goal,
and an origin (typed, or pulled from future-purchases). A flow converts to the series shape
app/recurring.py produces plus `origin`, so the Planning pages consume one list; a typed
flow steps by the calendar (the same day each month, clamped; two fixed days a month for
semimonthly; the anchor exactly once for `once`), a detected series by its median gap.
`due_dates()` and `occurrences_in_month()` dispatch on the origin so callers never ask: a
series tagged typed or future-purchases steps by the calendar, anything else like the
detector's.
Received is never here: it is the Category's actual income, read by the caller.
"""

import calendar
from datetime import UTC, date, datetime, timedelta

from . import recurring, registry
from .store.categories import categories
from .store.expected_flows import expected_flows
from .store.savings_goals import savings_goals
from .values import parse_amount, parse_date
from .web import DomainError

KINDS = ("income", "expense")
CADENCES = ("once", "weekly", "biweekly", "semimonthly", "monthly", "bimonthly", "quarterly",
            "semiyearly", "yearly", "irregular")
MONTH_STEP = {"monthly": 1, "bimonthly": 2, "quarterly": 3, "semiyearly": 6, "yearly": 12}
PER_MONTH = {"weekly": recurring.DAYS_PER_MONTH / 7, "biweekly": recurring.DAYS_PER_MONTH / 14,
             "semimonthly": 2.0, "monthly": 1.0, "bimonthly": 0.5, "quarterly": 1 / 3,
             "semiyearly": 1 / 6, "yearly": 1 / 12}
PERIOD_DAYS = {"weekly": 7.0, "biweekly": 14.0, "semimonthly": recurring.DAYS_PER_MONTH / 2,
               "monthly": recurring.DAYS_PER_MONTH, "bimonthly": 2 * recurring.DAYS_PER_MONTH,
               "quarterly": 3 * recurring.DAYS_PER_MONTH, "semiyearly": 6 * recurring.DAYS_PER_MONTH,
               "yearly": 365.25}
SEMIMONTHLY_GAP = 15
TYPED, PULLED, DETECTED = "typed", "future-purchases", "detected"
REGISTRY_ORIGINS = (TYPED, PULLED)     # a series without one of these steps like the detector's
REGISTRY = TYPED                       # kept for callers that compare against the old name


# --- calendar stepping ------------------------------------------------------------------

def _day(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def add_months(d: date, n: int) -> date:
    """The same day n months on, clamped to that month's length (31 Jan + 1 → 28/29 Feb)."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def occurrences(cadence: str, anchor: date):
    """Every occurrence from the anchor forward, by the calendar. `once` yields the anchor
    and stops. Semimonthly pays on the anchor's day and the day SEMIMONTHLY_GAP later each
    month (both clamped); an anchor day past the 15th pairs with the day fifteen earlier.
    Irregular yields nothing."""
    if cadence == "once":
        yield anchor
    elif cadence in ("weekly", "biweekly"):
        step = timedelta(days=7 if cadence == "weekly" else 14)
        d = anchor
        while True:
            yield d
            d += step
    elif cadence in MONTH_STEP:
        n = MONTH_STEP[cadence]
        i = 0
        while True:
            yield add_months(anchor, i * n)
            i += 1
    elif cadence == "semimonthly":
        first_day = anchor.day if anchor.day <= SEMIMONTHLY_GAP else anchor.day - SEMIMONTHLY_GAP
        base = anchor.replace(day=first_day)
        i = 0
        while True:
            month = add_months(base, i)
            last = calendar.monthrange(month.year, month.month)[1]
            for day in (first_day, min(first_day + SEMIMONTHLY_GAP, last)):
                d = month.replace(day=day)
                if d >= anchor:
                    yield d
            i += 1


def next_date(cadence: str, anchor: date | None, today: date) -> date | None:
    """The first occurrence on or after today; None for irregular, no anchor, or a `once`
    flow whose day has passed."""
    if cadence == "irregular" or anchor is None:
        return None
    for d in occurrences(cadence, anchor):
        if d >= today:
            return d
    return None


def registry_due_dates(cadence: str, anchor: date | None, start: date, end: date) -> list[date]:
    """Occurrences in (start, end]."""
    if cadence == "irregular" or anchor is None:
        return []
    out = []
    for d in occurrences(cadence, anchor):
        if d > end:
            break
        if d > start:
            out.append(d)
    return out


def registry_occurrences_in_month(cadence: str, anchor: date | None, ym: str) -> int:
    y, m = int(ym[:4]), int(ym[5:7])
    first = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return len(registry_due_dates(cadence, anchor, first - timedelta(days=1), end - timedelta(days=1)))


# --- one shape for both origins ------------------------------------------------------------

def as_series(flow: dict, today: date | datetime | None = None) -> dict:
    """A flow in the detector's series shape, with its origin and the planning fields."""
    today = _day(today) or datetime.now(UTC).date()
    cadence = flow.get("cadence") or "irregular"
    anchor = _day(flow.get("anchor_date"))
    amount = round(float(flow.get("amount") or 0), 2)
    nxt = next_date(cadence, anchor, today)
    per_month = round(amount * PER_MONTH[cadence], 2) if cadence in PER_MONTH else None
    origin = flow.get("origin") or TYPED
    return {
        "key": f"{origin}:{flow['_id']}", "id": flow["_id"], "label": flow.get("name") or "?",
        "kind": flow.get("kind") or "income",
        "category": flow.get("category") or None, "group": flow.get("group") or None,
        "cadence": cadence, "period_days": PERIOD_DAYS.get(cadence), "amount": amount,
        "first_date": anchor.isoformat() if anchor else None, "last_date": None,
        "next_date": nxt.isoformat() if nxt else None,
        "count": None, "expected_count": None, "confidence": None,
        "per_month": per_month, "spread": 0.0, "stable": True,
        "origin": origin, "active": bool(flow.get("active", True)),
        "notes": flow.get("notes") or None,
        "anchor_date": anchor.isoformat() if anchor else None,
        "day_known": bool(flow.get("day_known", True)),
        "month": anchor.strftime("%Y-%m") if anchor else None,
        "placed": anchor is not None,
        "goal_id": flow.get("goal_id") or None,
        "external_id": flow.get("external_id") or None,
        "external_status": flow.get("external_status") or None,
        "priority": flow.get("priority") or None,
        "done_at": _day(flow.get("done_at")).isoformat() if flow.get("done_at") else None,
    }


def due_dates(series: dict, start: date, end: date) -> list[date]:
    """The days a series is due in (start, end], by its origin's stepping."""
    if series.get("origin") in REGISTRY_ORIGINS:
        return registry_due_dates(series["cadence"], _day(series.get("anchor_date")), start, end)
    if not series.get("period_days") or not series.get("next_date"):
        return []
    step = timedelta(days=round(series["period_days"]))
    d = date.fromisoformat(series["next_date"])
    out = []
    while d <= end:
        if d > start:
            out.append(d)
        d += step
    return out


def occurrences_in_month(series: dict, ym: str) -> int:
    if series.get("origin") in REGISTRY_ORIGINS:
        return registry_occurrences_in_month(series["cadence"], _day(series.get("anchor_date")), ym)
    return recurring.occurrences_in_month(series, ym)


def planned_in_month(series: dict, ym: str) -> float:
    """What a flow puts into month ym: amount × occurrences (a `once` flow counts in its
    month only; irregular never)."""
    return round(series["amount"] * occurrences_in_month(series, ym), 2)


def merged_sources(today: datetime | None = None) -> list[dict]:
    """Income: active typed sources first, then the detected series whose Category no
    source claims, each tagged with its origin. The one list the Planning pages read."""
    today = today or datetime.now(UTC)
    typed = [as_series(s, today) for s in expected_flows.active("income")]
    claimed = {s["category"] for s in typed if s["category"]}
    detected = [{**s, "origin": DETECTED} for s in recurring.income_sources(today)
                if s["category"] not in claimed]
    return typed + detected


def planned_spend(today: datetime | None = None) -> list[dict]:
    """Expense: every active flow not yet done, placed or not, as series."""
    today = today or datetime.now(UTC)
    return [as_series(f, today) for f in expected_flows.active("expense")
            if not f.get("done_at")]


# --- the registry ------------------------------------------------------------------------

def income_categories() -> list[str]:
    """Income-typed Category names for the picker, sorted."""
    return sorted(c["_id"] for c in categories.list({"Type": "Income"}) if c.get("_id"))


def _check_category(name) -> str | None:
    name = (name or "").strip()
    if not name:
        return None
    if categories.get(name) is None:
        raise DomainError(f"unknown category '{name}'")
    return name


def _check_goal(goal_id) -> str | None:
    goal_id = (goal_id or "").strip()
    if not goal_id:
        return None
    if savings_goals.get(goal_id) is None:
        raise DomainError("unknown savings goal")
    return goal_id


def _check_cadence(v) -> str:
    v = (v or "").strip().lower()
    if v not in CADENCES:
        raise DomainError(f"cadence must be one of {', '.join(CADENCES)}")
    return v


def _check_kind(v) -> str:
    v = (v or "").strip().lower()
    if v not in KINDS:
        raise DomainError("kind must be income or expense")
    return v


def _check_month(v) -> str:
    v = (v or "").strip()
    if len(v) != 7 or v[4] != "-" or not (v[:4].isdigit() and v[5:].isdigit()) or not 1 <= int(v[5:]) <= 12:
        raise DomainError("month must be YYYY-MM")
    return v


def _placement(body: dict) -> dict:
    """anchor_date / day_known from a body carrying `anchor_date` (a day) or `month`
    (YYYY-MM, placed on the 1st with the day unknown; null unplaces)."""
    if "month" in body:
        if body["month"] in (None, ""):
            return {"anchor_date": None, "day_known": True}
        return {"anchor_date": f"{_check_month(body['month'])}-01", "day_known": False}
    if "anchor_date" in body:
        d = parse_date(body["anchor_date"], "anchor_date")
        return {"anchor_date": d, "day_known": d is not None}
    return {}


def list_flows(kind: str | None = None, today: datetime | None = None) -> list[dict]:
    """Every flow of a kind (active or not) as a series row, by name."""
    where = {"kind": kind} if kind else None
    return [as_series(f, today) for f in expected_flows.list(where, order=[("name", "asc")])]


def add_flow(body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise DomainError("name is required")
    amount = parse_amount(body.get("amount"), "amount")
    if amount <= 0:
        raise DomainError("amount must be positive")
    kind = _check_kind(body.get("kind", "income"))
    group = (body.get("group") or "").strip() or None
    if kind == "expense" and not group:
        raise DomainError("group is required for planned spend")
    fields = {
        "kind": kind, "name": name,
        "category": _check_category(body.get("category")),
        "group": group,
        "cadence": _check_cadence(body.get("cadence")),
        "amount": amount,
        "goal_id": _check_goal(body.get("goal_id")),
        "origin": body.get("origin") if body.get("origin") in (TYPED, PULLED) else TYPED,
        "external_id": (body.get("external_id") or "").strip() or None,
        "external_status": (body.get("external_status") or "").strip() or None,
        "pulled": body.get("pulled") if isinstance(body.get("pulled"), dict) else None,
        "priority": (body.get("priority") or "").strip() or None,
        "active": bool(body.get("active", True)),
        "notes": (body.get("notes") or "").strip() or None,
        "anchor_date": None, "day_known": True,
        **_placement(body),
    }
    return registry.add_doc(expected_flows, fields)


def update_flow(body: dict) -> dict:
    updates: dict = {}
    if "name" in body:
        name = (body["name"] or "").strip()
        if not name:
            raise DomainError("name cannot be blank")
        updates["name"] = name
    if "category" in body:
        updates["category"] = _check_category(body["category"])
    if "group" in body:
        updates["group"] = (body["group"] or "").strip() or None
    if "cadence" in body:
        updates["cadence"] = _check_cadence(body["cadence"])
    if "amount" in body:
        amount = parse_amount(body["amount"], "amount")
        if amount <= 0:
            raise DomainError("amount must be positive")
        updates["amount"] = amount
    if "goal_id" in body:
        updates["goal_id"] = _check_goal(body["goal_id"])
    if "active" in body:
        updates["active"] = bool(body["active"])
    if "notes" in body:
        updates["notes"] = (body["notes"] or "").strip() or None
    if "priority" in body:
        updates["priority"] = (body["priority"] or "").strip() or None
    if "external_status" in body:
        updates["external_status"] = (body["external_status"] or "").strip() or None
    if "pulled" in body and isinstance(body["pulled"], dict):
        updates["pulled"] = body["pulled"]
    if "done_at" in body:
        updates["done_at"] = parse_date(body["done_at"], "done_at")
    if "done_txn" in body:
        updates["done_txn"] = (body["done_txn"] or "").strip() or None
    updates.update(_placement(body))
    return registry.update_doc(expected_flows, body.get("id"), updates, "expected flow")


def delete_flow(body: dict) -> dict:
    return registry.delete_doc(expected_flows, body.get("id"), "expected flow")


def mark_done(flow_id: str, today: datetime | None = None) -> dict:
    """A done flow leaves the plan; its row stays for the record."""
    day = (today or datetime.now(UTC)).date().isoformat()
    return registry.update_doc(expected_flows, flow_id, {"done_at": day}, "expected flow")


# --- compatibility names (the Income page's API) --------------------------------------------

def list_sources(today: datetime | None = None) -> list[dict]:
    return list_flows("income", today)


def add_source(body: dict) -> dict:
    return add_flow({**body, "kind": "income"})


def update_source(body: dict) -> dict:
    return update_flow(body)


def delete_source(body: dict) -> dict:
    return delete_flow(body)
