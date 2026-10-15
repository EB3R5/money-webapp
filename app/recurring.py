"""Recurring series — income sources and bills found in the ledger (ADR-0021, D5).

detect() is a pure function over dated amounts grouped by a key: it reads a cadence off the
median gap between occurrences, takes the expected amount from the last three, and projects
the next date. Nothing is stored; every caller recomputes, so a series can never drift from
the ledger it was read from. The two loaders only choose rows: income by Category,
bills by a normalised merchant for Categories whose Timing says they recur (the Timing on a
transaction row is a stale Tiller copy, so it is read from the categories table).

Every number here is an estimate from the ledger and is labelled so wherever it is shown.
"""

import re
from datetime import date, datetime, timedelta
from statistics import median

from .rollup import DATED
from .simplefin.pending import normalize
from .store.transactions import transactions

# (name, min gap, max gap, period in days) — the band the median gap must fall in.
CADENCES = (
    ("weekly", 5, 9, 7.0),
    ("biweekly", 12, 16, 14.0),
    ("monthly", 26, 35, 30.44),
    ("quarterly", 80, 100, 91.3),
    ("semiyearly", 170, 195, 182.6),
    ("yearly", 350, 380, 365.25),
)
SLOW = {"quarterly", "semiyearly", "yearly"}          # two points are enough to see these
PERIODIC_TIMINGS = ("Monthly", "Weekly", "Quarterly", "Semi Yearly", "Yearly")
DAYS_PER_MONTH = 30.44
STABLE_SPREAD = 0.25     # (max − min) / median over the last three amounts: a bill holds still

_WEB_ID = re.compile(r"\bweb id:?.*$")
_PAYPAL = re.compile(r"^paypal (purchase|inst xfer)\b\s*")
_MASK = re.compile(r"^x{2,}\w*$")


def normalize_merchant(desc) -> str:
    """One key per merchant: lower-cased and whitespace-collapsed, without a 'web id: …'
    tail, a leading PayPal purchase / instant-transfer prefix, and any token that carries
    digits or an x-mask (card numbers, references, dates)."""
    s = _PAYPAL.sub("", _WEB_ID.sub("", normalize(desc)))
    tokens = [t for t in s.split(" ")
              if t and not any(ch.isdigit() for ch in t) and not _MASK.match(t)]
    return " ".join(tokens)


def cadence_of(gaps: list[float]) -> tuple[str, float] | None:
    """(name, period_days) for the band the median gap falls in, else None."""
    if not gaps:
        return None
    mid = median(gaps)
    for name, lo, hi, period in CADENCES:
        if lo <= mid <= hi:
            return name, period
    return None


def _day(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def detect(rows: list[dict], *, today, lookback_days: int = 730, min_count: int = 3) -> list[dict]:
    """Series from [{date, amount, key, label, category}] within `lookback_days` of today.

    Rows on the same day under one key are one occurrence (a split paycheck is still one
    paycheck). A series needs `min_count` occurrences, or two for quarterly and slower; a
    series whose last occurrence is more than two periods old has ended and is dropped. A
    series with occurrences but no recognisable gap is kept as "irregular" with no period,
    next date or per-month amount, so the caller can still show what it received."""
    today = _day(today)
    cutoff = today - timedelta(days=lookback_days)
    groups: dict = {}
    for r in rows:
        d = _day(r["date"])
        if d < cutoff or d > today:
            continue
        g = groups.setdefault(r["key"], {"days": {}, "label": None, "label_day": None,
                                         "category": r.get("category")})
        g["days"][d] = g["days"].get(d, 0.0) + float(r["amount"] or 0)
        if g["label_day"] is None or d >= g["label_day"]:
            g["label"], g["label_day"] = r.get("label") or r["key"], d

    out = []
    for key, g in groups.items():
        days = sorted(g["days"])
        count = len(days)
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        found = cadence_of(gaps)
        name, period = found if found else ("irregular", None)
        needed = 2 if name in SLOW else min_count
        if count < needed:
            continue
        last = days[-1]
        if period and (today - last).days > 2 * period:
            continue                                          # ended
        last_amounts = [abs(g["days"][d]) for d in days[-3:]]
        amount = round(median(last_amounts), 2)
        spread = (max(last_amounts) - min(last_amounts)) / amount if amount else 0.0
        next_date = None
        expected_count = None
        per_month = None
        if period:
            nxt = last + timedelta(days=round(period))
            while nxt < today:
                nxt += timedelta(days=round(period))
            next_date = nxt.isoformat()
            expected_count = round((last - days[0]).days / period + 1, 1)
            per_month = round(amount * DAYS_PER_MONTH / period, 2)
        out.append({
            "key": key, "label": g["label"], "category": g["category"],
            "cadence": name, "period_days": period, "amount": amount,
            "first_date": days[0].isoformat(), "last_date": last.isoformat(), "next_date": next_date,
            "count": count, "expected_count": expected_count,
            "confidence": round(min(1.0, count / expected_count), 2) if expected_count else None,
            "per_month": per_month,
            "spread": round(spread, 3), "stable": spread <= STABLE_SPREAD,
        })
    out.sort(key=lambda s: (-(s["per_month"] or 0), s["label"] or ""))
    return out


def occurrences_in_month(series: dict, ym: str) -> int:
    """How many times the series is due in calendar month ym, stepping by its period from
    the last occurrence in both directions but never before the first one (a month before
    the series began expects nothing). Monthly is one by definition (stepping 30.44 days
    lands twice in some months); irregular is zero."""
    period = series.get("period_days")
    if not period:
        return 0
    y, m = int(ym[:4]), int(ym[5:7])
    first_of = date(y, m, 1)
    end_of = date(y + (m == 12), m % 12 + 1, 1)
    first = date.fromisoformat(series["first_date"]) if series.get("first_date") else date.min
    if end_of <= first.replace(day=1):
        return 0
    if series["cadence"] == "monthly":
        return 1
    step = timedelta(days=round(period))
    last = date.fromisoformat(series["last_date"])
    hits = 0
    d = last
    while d >= first_of and d >= first:                    # backward, not past the first occurrence
        if d < end_of:
            hits += 1
        d -= step
    d = last + step
    while d < end_of:                                      # forward
        if d >= first_of:
            hits += 1
        d += step
    return hits


# --- loaders ----------------------------------------------------------------------------

_POSTED = "(pending IS NULL OR pending != 1)"


def income_sources(today) -> list[dict]:
    """Income-typed, posted, dated transactions grouped by Category."""
    rows = transactions.rows(
        f"SELECT date, amount, category FROM transactions WHERE type = 'Income' AND {_POSTED} "
        f"AND amount IS NOT NULL AND {DATED} AND category IS NOT NULL AND TRIM(category) <> ''")
    return detect([{"date": r["date"], "amount": r["amount"], "key": r["category"],
                    "label": r["category"], "category": r["category"]} for r in rows], today=today)


def bills(today) -> list[dict]:
    """Expense-typed outflows in Categories whose Timing recurs, grouped by merchant — and
    only the series whose amount holds still (`stable`). A gas station visited weekly sits
    in a Weekly category too, but its amount wanders; that is variable spend, not a bill,
    and the forecast's variable rate already carries it."""
    marks = ", ".join("?" for _ in PERIODIC_TIMINGS)
    dated = DATED.replace("date GLOB", "t.date GLOB")
    rows = transactions.rows(
        f"SELECT t.date, t.amount, t.description, t.category FROM transactions t "
        f"JOIN categories c ON c.id = t.category "
        f"WHERE t.type = 'Expense' AND t.amount < 0 AND c.timing IN ({marks}) "
        f"AND (t.pending IS NULL OR t.pending != 1) AND {dated}", list(PERIODIC_TIMINGS))
    found = detect([{"date": r["date"], "amount": r["amount"],
                     "key": normalize_merchant(r["description"]) or "(blank)",
                     "label": r["description"], "category": r["category"]} for r in rows], today=today)
    return [s for s in found if s["stable"]]
