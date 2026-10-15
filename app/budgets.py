"""Budget engine — seed planned amounts per spending Group from trailing history.

Over the transactions store: aggregate by (Group, month), keep groups with recent
activity, and seed each group's planned amount from its trailing-N-month average (the
method carried over from the household's earlier spreadsheet tooling).

A budget version is one row in `budgets` plus its lines in `budget_lines` (ADR-0012);
`load_budget()` hands it back in the shape the pages read:

    { _id: "bud_<hex>", budgetId: "BUD001", versionName, month: "YYYY-MM",
      status: "draft"|"saved",
      lines: [ { group, amount, source: "historical"|"manual", dataPoints } ],
      _created_at, _edited_at }

Every version is preserved (browse/reopen), mirroring v2's append-only Budget_Planning.
"""

import re
import secrets
from datetime import UTC, date, datetime

from . import rollup
from .pivot import pivot
from .store.budget_lines import budget_lines
from .store.budgets import budgets
from .store.categories import categories

# Ported verbatim from Budget v2 config.js.
TRAILING_MONTHS = 6           # months of history averaged into a seeded amount
ACTIVE_LOOKBACK_MONTHS = 12   # a group must have activity inside this window to be seeded
ID_PREFIX = "BUD"
ID_LENGTH = 3

# Budget-vs-Actual alert thresholds (fraction of budget), from v2 ALERT_THRESHOLDS.
ALERT_CRITICAL = 0.25
ALERT_HIGH = 0.15
ALERT_MEDIUM = 0.05


def _round2(n: float) -> float:
    return round(n * 100) / 100


def current_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _cutoff_month(lookback: int) -> str:
    """The YYYY-MM `lookback` months before today (inclusive boundary, like v2)."""
    today = date.today()
    m = today.month - lookback
    y = today.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def aggregate_by_group() -> dict:
    """transactions → { group: [ {month, total, count}, ... ] } sorted by month asc.

    The month-dimensioned sum comes from the shared cashflow rollup; blank groups are
    dropped here, matching v2's skip rules."""
    rows = rollup.totals_by_month("Group", nonblank=["Group"])
    by_group: dict = {}
    for row in rows:
        g = (row["Group"] or "").strip()
        if not g or not row["month"]:
            continue
        by_group.setdefault(g, []).append(
            {"month": row["month"], "total": row["total"], "count": row["count"]})
    return by_group


def _trailing_average(entries: list, months: int = TRAILING_MONTHS) -> dict:
    """Average the last `months` monthly totals (v2 requires >= 2 data points)."""
    if entries and len(entries) >= 2:
        recent = entries[-months:]
        avg = sum(e["total"] for e in recent) / len(recent)
        return {"amount": _round2(avg), "source": "historical", "dataPoints": len(recent)}
    return {"amount": 0.0, "source": "manual", "dataPoints": len(entries or [])}


def generate_draft_lines() -> list:
    """Seed one line per active group from its trailing average, ranked by spend desc.

    Active = has at least one month inside ACTIVE_LOOKBACK_MONTHS (v2 getActiveGroups).
    Returns [{ group, amount, source, dataPoints }]."""
    by_group = aggregate_by_group()
    cutoff = _cutoff_month(ACTIVE_LOOKBACK_MONTHS)

    scored = []
    for group, entries in by_group.items():
        recent = [e for e in entries if e["month"] >= cutoff]
        if not recent:
            continue
        spend = sum(abs(e["total"]) for e in recent)
        avg = _trailing_average(entries)
        scored.append({"group": group, "amount": avg["amount"], "source": avg["source"],
                       "dataPoints": avg["dataPoints"], "_spend": spend})

    scored.sort(key=lambda r: r["_spend"], reverse=True)
    for r in scored:
        del r["_spend"]
    return scored


def next_budget_id() -> str:
    """BUD001, BUD002, … one past the current max across every version."""
    biggest = 0
    for bid in budgets.distinct("budgetId"):
        bid = bid or ""
        if bid.startswith(ID_PREFIX):
            try:
                biggest = max(biggest, int(bid[len(ID_PREFIX):]))
            except ValueError:
                pass
    return ID_PREFIX + str(biggest + 1).zfill(ID_LENGTH)


def create_draft(month: str, version_name: str) -> dict:
    """Build a draft budget seeded from history and insert it. Returns the new doc."""
    month = (month or "").strip() or current_month()
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("month must be YYYY-MM")
    version_name = (version_name or "").strip() or "Baseline"

    lines = generate_draft_lines()
    now = datetime.now(UTC)
    doc = {
        "_id": "bud_" + secrets.token_hex(8),
        "budgetId": next_budget_id(),
        "versionName": version_name,
        "month": month,
        "status": "draft",
        "_created_at": now,
        "_edited_at": now,
    }
    budgets.insert(doc)
    budget_lines.insert_many(
        {"budget": doc["_id"], "position": i, **line} for i, line in enumerate(lines))
    return {**doc, "lines": lines}


def load_budget(budget_id: str) -> dict | None:
    """One version with its lines embedded in position order; None if unknown."""
    doc = budgets.get(budget_id)
    if doc is None:
        return None
    return {**doc, "lines": budget_lines.for_budget(budget_id)}


def list_versions() -> list:
    """All saved + draft budgets, newest first, with line count + total for the table."""
    lines_by = budget_lines.by_budget()
    out = []
    for d in budgets.list(order=[("_created_at", "desc")]):
        lines = lines_by.get(d["_id"], [])
        out.append({
            "id": d["_id"],
            "budgetId": d.get("budgetId", ""),
            "versionName": d.get("versionName", ""),
            "month": d.get("month", ""),
            "status": d.get("status", "draft"),
            "groups": len(lines),
            "total": _round2(sum(float(l.get("amount") or 0) for l in lines)),
            "created": (d.get("_created_at") or datetime.now(UTC)).strftime("%Y-%m-%d"),
        })
    return out


KIND_SECTION = {"income": "Income", "expense": "Expense"}
SECTION_ORDER = ["Income", "Expense", "Other"]


def fmt_class(verdict: dict) -> str:
    """Conditional-format CSS class for a Budget-vs-Actual cell, from assess()'s verdict:
    on-target = neutral, favourable = green, unfavourable = amber→red by severity."""
    label = verdict["label"]
    if label == "On Target":
        return "bva-ok"
    if verdict["favorable"]:
        return "bva-good"
    return {"Medium": "bva-bad1", "High": "bva-bad2",
            "Critical": "bva-bad3"}.get(label.split()[0], "bva-bad2")


def build_version_pivot() -> dict:
    """Budget-vs-Actual pivot across every version. Rows = Group (bucketed into Income /
    Expense / Other), columns = each version, with two measures per version: planned Budget
    and the Actual aggregated from transactions for that version's month. Each Actual cell
    carries a conditional-format class from assess() (favourability + severity).

    Reuses app/pivot.py for the per-column subtotal/total maths (column keys are
    "<version_id>|b" for budget and "<version_id>|a" for actual). The pivot's `grand` mixes
    measures and is ignored by the view; per-version column totals are what's shown.

    As in build_report, a Group with activity in a version's month but no line in that
    version still appears: budget 0 (rendered "–"), the actual from history, and the
    "bva-unb" (unbudgeted) format class instead of a verdict.

    Returns { versions: [{key, label, month, budgetId}], table: <pivot result> }."""
    kinds = rollup.group_kinds()
    history = aggregate_by_group()           # {group: [{month, total, count}]}
    lines_by = budget_lines.by_budget()

    def _row(g):
        return rows.setdefault(g, {"group": g, "budget": {}, "actual": {}, "cells": {}, "fmt": {}})

    def _actual(g, month):
        return _round2(next((e["total"] for e in history.get(g, []) if e["month"] == month), 0.0))

    versions, rows, unbudgeted = [], {}, set()
    for b in budgets.list(order=[("month", "asc"), ("_created_at", "asc")]):
        key, month = b["_id"], b.get("month", "")
        versions.append({"key": key, "label": b.get("versionName") or b.get("budgetId") or "Budget",
                         "month": month, "budgetId": b.get("budgetId", "")})
        lined = set()
        for line in lines_by.get(key, []):
            g = (line.get("group") or "").strip()
            if not g:
                continue
            lined.add(g)
            row = _row(g)
            budget_amt = _round2(float(line.get("amount") or 0))
            actual = _actual(g, month)
            row["budget"][key], row["actual"][key] = budget_amt, actual
            row["cells"][key + "|b"], row["cells"][key + "|a"] = budget_amt, actual
        # Activity this month with no line in this version.
        for g, entries in history.items():
            if g in lined or not any(e["month"] == month for e in entries):
                continue
            row = _row(g)
            actual = _actual(g, month)
            row["budget"][key], row["actual"][key] = 0.0, actual
            row["cells"][key + "|b"], row["cells"][key + "|a"] = 0.0, actual
            unbudgeted.add((g, key))

    # Kind + per-version Budget-vs-Actual verdict (or the unbudgeted marker).
    for g, row in rows.items():
        row["kind"] = _kind_of(history.get(g, []), g, kinds)
        for v in versions:
            k = v["key"]
            if (g, k) in unbudgeted:
                row["fmt"][k] = "bva-unb"
            elif k in row["budget"]:
                row["fmt"][k] = fmt_class(assess(row["budget"][k], row["actual"][k], row["kind"]))

    cols = [k for v in versions for k in (v["key"] + "|b", v["key"] + "|a")]
    table = pivot(
        list(rows.values()), columns=cols,
        section_of=lambda r: KIND_SECTION.get(r["kind"], "Other"),
        values_of=lambda r: r["cells"],
        sort_of=lambda r: sum(r["budget"].values()),
        section_order=SECTION_ORDER,
    )
    return {"versions": versions, "table": table}


def all_groups() -> list:
    """Distinct Group names from the categories store — for the add-line picker."""
    groups = categories.distinct("Group")
    return sorted(g for g in groups if g and isinstance(g, str))


# --- Budget vs Actual report ------------------------------------------------

def _kind_of(entries: list, group: str, kinds: dict) -> str:
    """A group's income/expense kind for Budget-vs-Actual favourability.

    Budget v2 judged variance off the raw sign of (actual − budget), which is backwards
    for income: earning less than your income target is *under* budget and unfavorable,
    not 'Over'. The kind comes from rollup.group_kinds() (majority category Type), but a
    group whose historical money is clearly positive reads as income even when its
    metadata is missing or wrong; kindless groups default to expense."""
    net = sum(e["total"] for e in entries)
    return "income" if net > 0 else (kinds.get(group) or "expense")


def assess(budget_amt: float, actual_amt: float, kind: str) -> dict:
    """Variance verdict that respects whether a group is income or expense.

    Direction is by magnitude (|actual| vs |budget|): spending/earning more than planned
    is 'Over', less is 'Under'. Favourability is kind-aware: for an expense, under budget
    is good; for income, over budget (earning more) is good. Severity uses v2's 5/15/25%
    bands. Returns { label, favorable }."""
    b, a = abs(budget_amt), abs(actual_amt)
    over = a > b
    favorable = over if kind == "income" else not over

    if b == 0:
        return {"label": "On Target", "favorable": True}
    mag_pct = abs(a - b) / b
    if mag_pct <= ALERT_MEDIUM:
        return {"label": "On Target", "favorable": favorable}
    severity = "Critical" if mag_pct > ALERT_CRITICAL else "High" if mag_pct > ALERT_HIGH else "Medium"
    return {"label": f"{severity} {'Over' if over else 'Under'}", "favorable": favorable}


def build_report(budget: dict) -> list:
    """Compare one budget version's planned amounts against actual spend per group.

    The row universe is the union of the version's lines and the Groups with activity in
    its month, so spend with no line is reported instead of dropped. Each row carries
    `match`: "both" (line and activity), "budget_only" (line, no spend — the usual
    "Critical Under"), or "actual_only" (spend, no line — verdict "Unbudgeted", favorable
    only for income, no pct/score since there is no plan to score against). A genuine
    zero-amount line keeps the "On Target" verdict. Transactions with a blank Group are
    outside the report (that is a data-health concern, not a budgeting one).

    Returns rows: month, group, kind, version, match, budget_amount, actual_amount,
    variance, variance_pct, score, alert_level, favorable — sorted by budget amount asc
    (v2 order) with actual-only rows last."""
    by_group = aggregate_by_group()
    kinds = rollup.group_kinds()
    month = budget.get("month", "")
    version = budget.get("versionName", "")

    lines = {}
    for line in budget.get("lines") or []:
        g = (line.get("group") or "").strip()
        if g:
            lines[g] = line
    active = {g for g, entries in by_group.items() if any(e["month"] == month for e in entries)}
    groups = list(lines) + sorted(active - set(lines))

    rows = []
    for group in groups:
        line = lines.get(group)
        b_amt = float(line.get("amount") or 0) if line else 0.0
        entries = by_group.get(group, [])
        actual = next((e["total"] for e in entries if e["month"] == month), 0.0)
        kind = _kind_of(entries, group, kinds)
        variance = actual - b_amt

        if line is None:
            match = "actual_only"
            verdict = {"label": "Unbudgeted", "favorable": kind == "income"}
            variance_pct, score = None, None
        else:
            match = "both" if actual != 0 else "budget_only"
            verdict = assess(b_amt, actual, kind)
            # Signed pct: keeps the red→green gradient favourability-aligned for both kinds.
            variance_pct = variance / abs(b_amt) if b_amt != 0 else 0.0
            score = round(max(0, 100 - abs(variance_pct) * 100)) if b_amt != 0 else 50

        rows.append({
            "month": month, "group": group, "kind": kind, "version": version, "match": match,
            "budget_amount": _round2(b_amt), "actual_amount": _round2(actual),
            "variance": _round2(variance), "variance_pct": variance_pct,
            "score": score, "alert_level": verdict["label"], "favorable": verdict["favorable"],
        })

    rows.sort(key=lambda r: (r["match"] == "actual_only", r["budget_amount"]))
    return rows
