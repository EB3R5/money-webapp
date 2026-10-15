"""Credit — credit-card registry, scores, activity log, and payoff strategy over the stores
(logic carried over from the household's earlier spreadsheet tooling).

Where each piece of data lives:

* SHARED — already in the app's data, derived live, never re-stored:
    - credit-card **balances** ← balance history (newest Snapshot per account); joined to a
      registry card by an alias (`balance_account`) to handle messy names like
      "Everyday Card" vs "EVERYDAY CARD (1234…)". Utilization = |balance| ÷ credit_limit.
    - credit-card **payments** ← transactions where Group=="Credit Card".

* CREDIT-SPECIFIC manual data — has no other home, stored in its own tables:
    - `credit_accounts`  — the registry: limit, APR, min payment, annual fee, opened, status.
    - `credit_scores`    — timestamped score log per bureau.
    - `credit_activity`  — inquiries / disputes / negative items (Falls-Off date derived).

* STATIC reference — code constants below (the FICO score bands and factors, what-if scenarios).
* COMPUTED live — credit_summary() and strategy(); nothing stored.
"""

from datetime import UTC, date, datetime

from . import registry
from .store.balance_history import balance_history
from .store.credit_accounts import credit_accounts
from .store.credit_activity import credit_activity
from .store.credit_scores import credit_scores
from .store.transactions import transactions
from .values import parse_amount, parse_date
from .web import DomainError

DEFAULT_CONFIG = {"score_target": 800}
CONFIG = registry.ConfigDoc("credit", DEFAULT_CONFIG)

# Statuses that count as live for summary/strategy ('Active' on older rows; real data has 'Open').
ACTIVE_STATUSES = {"active", "open"}

# Years until a credit event falls off the report, by Activity category (Config.FALLOFF_YEARS).
FALLOFF_YEARS = {
    "Hard Inquiry": 2, "Soft Inquiry": 0, "Negative Item": 7, "Dispute": 0,
    "Application": 0, "Limit Increase": 0, "Account Change": 0,
}

# The FICO score bands, as the bureaus publish them.
MILESTONES = [
    {"phase": "Fair", "score": 580},
    {"phase": "Good", "score": 670},
    {"phase": "Very good", "score": 740},
    {"phase": "Exceptional", "score": 800},
]

FICO_FACTORS = [
    {"factor": "Payment History", "weight": 0.35, "target": "100% On-Time",
     "action": "Set up autopay on all accounts"},
    {"factor": "Credit Utilization", "weight": 0.30, "target": "< 10%",
     "action": "Pay balances below 10%; request limit increases"},
    {"factor": "Length of Credit History", "weight": 0.15, "target": "7+ Years Avg",
     "action": "Keep oldest accounts open"},
    {"factor": "Credit Mix", "weight": 0.10, "target": "3–5 Types",
     "action": "Add installment/builder loan if missing"},
    {"factor": "New Credit Inquiries", "weight": 0.10, "target": "< 2 in 12 mo",
     "action": "Limit applications; use pre-qual tools"},
]

# What-if rows the Strategy section works through against the live totals.
UTILIZATION_SCENARIOS = [
    {"label": "Current state", "balance_adjust": 0, "limit_adjust": 0, "impact": "Baseline", "action": "—"},
    {"label": "Pay down $500", "balance_adjust": -500, "limit_adjust": 0, "impact": "Moderate", "action": "Pay an extra $500 this month"},
    {"label": "Pay down $1,000", "balance_adjust": -1000, "limit_adjust": 0, "impact": "Good", "action": "A larger paydown"},
    {"label": "Pay down $2,000", "balance_adjust": -2000, "limit_adjust": 0, "impact": "High", "action": "A major paydown"},
    {"label": "Limit increase +$2,000", "balance_adjust": 0, "limit_adjust": 2000, "impact": "Moderate", "action": "Ask for a limit increase on the main card"},
    {"label": "Limit increase +$5,000", "balance_adjust": 0, "limit_adjust": 5000, "impact": "Good", "action": "A new card, or a large limit increase"},
    {"label": "Pay down $500 + limit +$2,000", "balance_adjust": -500, "limit_adjust": 2000, "impact": "Best", "action": "Combine a paydown with a limit request"},
]


# --- shared helpers ---------------------------------------------------------

def _amount(v, field):
    """Optional money field — blank stays None (an unset limit/fee, not zero)."""
    return parse_amount(v, field, blank=None)


def _rate(v, field):
    """Percent (24.9) or fraction (0.249) → fraction, or None when blank."""
    if v in (None, ""):
        return None
    try:
        r = float(str(v).replace("%", "").strip())
    except (TypeError, ValueError):
        raise DomainError(f"{field} must be a number")
    if r > 1:
        r = r / 100
    return round(r, 4)


def _is_active(status):
    return (status or "").strip().lower() in ACTIVE_STATUSES


def _iso(v):
    """Store dates come back as date objects; the page and the API speak ISO strings."""
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _age_years(opened):
    if not opened:
        return None
    try:
        d = datetime.strptime(str(opened)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    return (datetime.now(UTC) - d).days / 365.25


# --- config -----------------------------------------------------------------

def get_config() -> dict:
    return CONFIG.get()


def set_config(body: dict) -> dict:
    cfg = CONFIG.get()
    if "score_target" in body:
        cfg["score_target"] = int(_amount(body["score_target"], "score_target") or 0)
    return CONFIG.save(cfg)


# --- shared balances (from balance history) ---------------------------------

def _latest_balances() -> dict:
    """{account_name: latest Balance} — newest Snapshot per account. The shared credit
    balances; a registry card reads its own via the balance_account alias."""
    return balance_history.latest_by_account()


def balance_account_options() -> list:
    return balance_history.account_names()


# --- accounts registry (CRUD) -----------------------------------------------

def _serialize_account(doc: dict, balances: dict) -> dict:
    alias = doc.get("balance_account") or doc.get("name")
    snap = balances.get(alias)
    owed = round(abs(snap["balance"]), 2) if snap and snap["balance"] is not None else None
    limit = doc.get("credit_limit")
    util = round(owed / limit, 4) if (owed is not None and limit) else None
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "type": doc.get("type"),
        "opened_date": _iso(doc.get("opened_date")),
        "credit_limit": limit,
        "apr": doc.get("apr"),
        "min_payment": doc.get("min_payment"),
        "annual_fee": doc.get("annual_fee"),
        "status": doc.get("status"),
        "balance_account": doc.get("balance_account"),
        "notes": doc.get("notes"),
        "balance": owed,
        "utilization": util,
        "balance_as_of": _iso(snap["date"])[:10] if snap and snap.get("date") else None,
        "active": _is_active(doc.get("status")),
    }


def list_accounts(include_closed: bool = False) -> list:
    """Registry cards, joined to their latest balances. Explicitly Closed entries
    (archived linked accounts) are hidden by default; blank/legacy statuses stay."""
    balances = _latest_balances()
    out = []
    for d in credit_accounts.list(order=[("name", "asc")]):
        if not include_closed and (d.get("status") or "").strip().lower() == "closed":
            continue
        out.append(_serialize_account(d, balances))
    return out


# One parser per registry field; add coerces every field, update only the ones sent.
_ACCOUNT_FIELDS = {
    "name": lambda v: (v or "").strip(),
    "type": lambda v: (v or "").strip() or None,
    "opened_date": lambda v: parse_date(v, "opened_date"),
    "credit_limit": lambda v: _amount(v, "credit_limit"),
    "apr": lambda v: _rate(v, "apr"),
    "min_payment": lambda v: _amount(v, "min_payment"),
    "annual_fee": lambda v: _amount(v, "annual_fee"),
    "status": lambda v: (v or "").strip() or "Active",
    "balance_account": lambda v: (v or "").strip() or None,
    "notes": lambda v: (v or "").strip() or None,
}


def _account_fields(body: dict, *, only_sent: bool = False) -> dict:
    keys = [k for k in _ACCOUNT_FIELDS if not only_sent or k in body]
    fields = {k: _ACCOUNT_FIELDS[k](body.get(k)) for k in keys}
    if "name" in fields and not fields["name"]:
        raise DomainError("name is required")
    return fields


def add_account(body: dict) -> dict:
    return registry.add_doc(credit_accounts, _account_fields(body))


def update_account(body: dict) -> dict:
    fields = _account_fields(body, only_sent=True)
    return registry.update_doc(credit_accounts, body.get("id"), fields, "account")


def delete_account(body: dict) -> dict:
    return registry.delete_doc(credit_accounts, body.get("id"), "account")


# --- credit score log (CRUD) ------------------------------------------------

def list_scores() -> list:
    return [{"id": str(d["_id"]), "date": _iso(d.get("date")), "bureau": d.get("bureau"),
             "score": d.get("score"), "change": d.get("change"), "notes": d.get("notes")}
            for d in credit_scores.list(order=[("date", "asc")])]


def add_score(body: dict) -> dict:
    score = _amount(body.get("score"), "score")
    if not score:
        raise DomainError("score is required")
    return registry.add_doc(credit_scores, {
        "date": parse_date(body.get("date")) or datetime.now(UTC).date().isoformat(),
        "bureau": (body.get("bureau") or "").strip() or None,
        "score": int(score),
        "change": _amount(body.get("change"), "change"),
        "notes": (body.get("notes") or "").strip() or None,
    })


def delete_score(body: dict) -> dict:
    return registry.delete_doc(credit_scores, body.get("id"), "score")


# --- activity log (CRUD) ----------------------------------------------------

def _falls_off(category, date):
    yrs = FALLOFF_YEARS.get((category or "").strip())
    if not yrs or not date:
        return None
    y, m, d = (int(x) for x in str(date)[:10].split("-"))
    return f"{y + yrs}-{m:02d}-{d:02d}"


def list_activity() -> list:
    return [{
        "id": str(d["_id"]), "date": _iso(d.get("date")), "category": d.get("category"),
        "creditor": d.get("creditor"), "bureau": d.get("bureau"), "type": d.get("type"),
        "amount": d.get("amount"), "status": d.get("status"), "result": d.get("result"),
        "falls_off": _falls_off(d.get("category"), _iso(d.get("date"))), "notes": d.get("notes"),
    } for d in credit_activity.list(order=[("date", "desc")])]


def add_activity(body: dict) -> dict:
    fields = {
        "date": parse_date(body.get("date")) or datetime.now(UTC).date().isoformat(),
        "category": (body.get("category") or "").strip() or None,
        "creditor": (body.get("creditor") or "").strip() or None,
        "bureau": (body.get("bureau") or "").strip() or None,
        "type": (body.get("type") or "").strip() or None,
        "amount": _amount(body.get("amount"), "amount"),
        "status": (body.get("status") or "").strip() or None,
        "result": (body.get("result") or "").strip() or None,
        "notes": (body.get("notes") or "").strip() or None,
    }
    if not fields["category"]:
        raise DomainError("category is required")
    return registry.add_doc(credit_activity, fields)


def delete_activity(body: dict) -> dict:
    return registry.delete_doc(credit_activity, body.get("id"), "activity")


# --- shared payments (from transactions) ------------------------------------

def payment_totals() -> dict:
    """Credit-card payment totals 30/90/all from transactions (Group=="Credit Card"),
    summed as |amount| so payments read as money paid, not signed outflows."""
    now = datetime.now(UTC)
    d30 = d90 = total = 0.0
    for when, amount in transactions.dated_amounts(group="Credit Card"):
        if not isinstance(when, datetime):
            continue
        amt = abs(amount)
        days = (now - when.replace(tzinfo=UTC)).days
        total += amt
        if days <= 90:
            d90 += amt
        if days <= 30:
            d30 += amt
    return {"d30": round(d30, 2), "d90": round(d90, 2), "all": round(total, 2)}


# --- computed: credit summary -----------------------------------------------

def _score_section(scores: list, target: int) -> dict:
    vals = [s["score"] for s in scores if s.get("score")]
    starting = vals[0] if vals else 0
    current = vals[-1] if vals else 0
    span = target - starting
    current_ms = next((m["phase"] for m in reversed(MILESTONES) if current >= m["score"]), None)
    next_ms = next((m for m in MILESTONES if current < m["score"]), None)
    return {
        "current": current, "starting": starting, "target": target,
        "gained": current - starting, "remaining": target - current,
        "pct": round((current - starting) / span, 4) if span > 0 else 0.0,
        "milestone": current_ms,
        "next_milestone": f"{next_ms['phase']} ({next_ms['score']})" if next_ms else "Top band reached",
    }


def credit_summary() -> dict:
    cfg = get_config()
    accounts = list_accounts()
    active = [a for a in accounts if a["active"]]

    total_limit = sum(a["credit_limit"] or 0 for a in active)
    total_balance = sum(a["balance"] or 0 for a in active)
    total_min = sum(a["min_payment"] or 0 for a in active)
    total_fees = sum(a["annual_fee"] or 0 for a in active)
    apr_numer = sum((a["apr"] or 0) * (a["balance"] or 0) for a in active)
    over_30 = [a["name"] for a in active if a["utilization"] and a["utilization"] > 0.30]
    highest = max((a for a in active if a["utilization"] is not None),
                  key=lambda a: a["utilization"], default=None)
    ages = [_age_years(a["opened_date"]) for a in active]
    ages = [x for x in ages if x is not None]

    overall_util = round(total_balance / total_limit, 4) if total_limit else 0.0
    scores = list_scores()
    activity = list_activity()
    now = datetime.now(UTC)

    def _within(months, cat):
        out = 0
        for a in activity:
            if (a["category"] or "") != cat or not a["date"]:
                continue
            d = datetime.strptime(a["date"][:10], "%Y-%m-%d").replace(tzinfo=UTC)
            if (now - d).days <= months * 30.44:
                out += 1
        return out

    fico_status = {
        "Credit Utilization": "✅" if overall_util <= 0.10 else "🔄" if overall_util <= 0.30 else "⚠️",
        "Length of Credit History": "✅" if (ages and sum(ages) / len(ages) >= 7)
            else "🔄" if (ages and sum(ages) / len(ages) >= 3) else "⏳",
        "New Credit Inquiries": "✅" if _within(12, "Hard Inquiry") <= 1
            else "🔄" if _within(12, "Hard Inquiry") <= 3 else "⚠️",
    }

    return {
        "score": _score_section(scores, cfg["score_target"]),
        "accounts": {
            "count": len(active),
            "total_limit": round(total_limit, 2),
            "total_balance": round(total_balance, 2),
            "overall_util": overall_util,
            "over_30": over_30,
            "highest": {"name": highest["name"], "util": highest["utilization"]} if highest else None,
            "total_min": round(total_min, 2),
            "total_fees": round(total_fees, 2),
            "weighted_apr": round(apr_numer / total_balance, 4) if total_balance else 0.0,
            "avg_age": round(sum(ages) / len(ages), 1) if ages else 0.0,
        },
        "activity": {
            "hard_12": _within(12, "Hard Inquiry"),
            "hard_24": _within(24, "Hard Inquiry"),
            "open_disputes": sum(1 for a in activity
                                 if a["category"] == "Dispute" and (a["status"] or "").lower() == "open"),
            "neg_items": sum(1 for a in activity if a["category"] == "Negative Item"),
        },
        "payments": payment_totals(),
        "fico": [{**f, "status": fico_status.get(f["factor"], "—")} for f in FICO_FACTORS],
    }


# --- computed: strategy -----------------------------------------------------

import math


def _months_to_payoff(balance, apr, min_payment):
    rate = (apr or 0) / 12
    if min_payment and rate > 0 and min_payment > balance * rate:
        return math.ceil(-math.log(1 - (balance * rate) / min_payment) / math.log(1 + rate))
    if min_payment:
        return math.ceil(balance / min_payment)
    return None


def strategy() -> dict:
    accounts = [a for a in list_accounts() if a["active"]]
    total_limit = sum(a["credit_limit"] or 0 for a in accounts)
    total_balance = sum(a["balance"] or 0 for a in accounts)

    scenarios = []
    for s in UTILIZATION_SCENARIOS:
        bal = max(0.0, total_balance + s["balance_adjust"])
        lim = total_limit + s["limit_adjust"]
        scenarios.append({"label": s["label"], "limit": round(lim, 2), "balance": round(bal, 2),
                          "util": round(bal / lim, 4) if lim > 0 else 0.0,
                          "impact": s["impact"], "action": s["action"]})

    payoff = []
    for a in sorted((a for a in accounts if (a["balance"] or 0) > 0),
                    key=lambda a: a["apr"] or 0, reverse=True):
        bal, apr, minp = a["balance"], a["apr"] or 0, a["min_payment"] or 0
        monthly_interest = round(bal * apr / 12, 2)
        months = _months_to_payoff(bal, apr, minp)
        payoff.append({
            "name": a["name"], "balance": bal, "apr": apr, "min_payment": minp,
            "monthly_interest": monthly_interest, "months": months,
            "total_interest": round(months * monthly_interest, 2) if months else None,
            "strategy": "Avalanche — pay first (highest APR)" if apr > 0.20
                else "Snowball — quick win" if bal < 500 else "Standard minimum",
        })
    for i, p in enumerate(payoff):
        p["priority"] = i + 1

    return {
        "utilization_scenarios": scenarios,
        "payoff": {
            "rows": payoff,
            "totals": {"balance": round(sum(p["balance"] for p in payoff), 2),
                       "min_payment": round(sum(p["min_payment"] for p in payoff), 2),
                       "monthly_interest": round(sum(p["monthly_interest"] for p in payoff), 2)},
        },
    }
