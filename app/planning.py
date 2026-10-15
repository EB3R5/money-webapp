"""Planning — the facts behind the Planning section's pages (ADR-0021).

One function, month_facts(), owns a month's numbers so the Month, Notebook and Planner pages
show the same figures: income and expense through the Cashflow rollup (Type rule), the net
savings rate as net ÷ income (D3, distinct from the Savings page's mapping-driven rate), the
budget picked by budget_for_month() (D4) with Budget-vs-Actual rows from the budgets engine,
and Net worth through app.networth (D2). Nothing here writes.
"""

import calendar
import re
from datetime import UTC, date, datetime, timedelta

from . import budgets as engine
from . import documents, expected_flows, networth, reconcile, recurring, rollup, savings
from .networth import prev_month
from .pivot import pivot
from .config import FUTURE_PURCHASES_URL
from .store.accounts import accounts
from .store.budgets import budgets
from .store.deletions import deletions
from .store.journal_entries import journal_entries
from .store.sync_runs import sync_runs
from .store.transactions import transactions
from .web import DomainError

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
YEAR_RE = re.compile(r"^\d{4}$")
SERIES_MONTHS = 12
MISSES = 4
UNBUDGETED_FLOOR = 25.0      # ignore unbudgeted spend under this (a coffee is not a prompt)
OVER_PCT = 0.15              # a line at least this far over its budget gets a prompt
STREAK = 3                   # months running
BODY_LIMIT = 1_000_000

__all__ = ["is_month", "is_year", "is_period", "month_label", "prev_month", "next_month",
           "days_in", "budget_for_month", "budget_report", "month_facts", "figures_for",
           "prompts", "addressed", "month_prompts",
           "is_open", "get_entry", "save_entry", "refreeze", "delete_entry",
           "notebook_blocks", "notebook_rail", "notebook_view", "sparkline"]


def is_month(s: str | None) -> bool:
    return bool(s) and MONTH_RE.match(s) is not None


def is_year(s: str | None) -> bool:
    return bool(s) and YEAR_RE.match(s) is not None


def is_period(s: str | None) -> bool:
    """A journal period: a month ('YYYY-MM') or a year review ('YYYY')."""
    return is_month(s) or is_year(s)


def month_label(ym: str) -> str:
    """'2026-09' → 'September 2026'."""
    return f"{calendar.month_name[int(ym[5:7])]} {ym[:4]}"


def next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def days_in(ym: str) -> int:
    return calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]


def _r2(v) -> float:
    return round(float(v or 0), 2)


# --- budget ---------------------------------------------------------------------------

def budget_for_month(ym: str) -> dict | None:
    """D4: the newest saved version for the month, else the newest draft, else None. The
    version comes back with its lines, ready for the engine's build_report()."""
    versions = budgets.list({"month": ym}, order=[("_created_at", "desc")])
    saved = [v for v in versions if v.get("status") == "saved"]
    pick = (saved or versions or [None])[0]
    return engine.load_budget(pick["_id"]) if pick else None


def pill(row: dict) -> dict:
    """The status pill for a Budget-vs-Actual row: {text, cls}. Text follows the engine's
    verdict; cls is ok / over / warn / none so the page needs no colour logic of its own."""
    if row["match"] == "actual_only":
        return {"text": "unbudgeted", "cls": "warn"}
    if row["match"] == "budget_only":
        return {"text": "no activity", "cls": "none"}
    if row["alert_level"] == "On Target":
        return {"text": "on target", "cls": "ok"}
    return {"text": row["alert_level"].lower(), "cls": "ok" if row["favorable"] else "over"}


def planned_by_group(ym: str, today: datetime | None = None) -> dict:
    """{Group: planned spend placed in ym} from the active expense flows (#183)."""
    out: dict = {}
    for f in expected_flows.planned_spend(today):
        if not f["placed"] or not f["group"]:
            continue
        amt = expected_flows.planned_in_month(f, ym)
        if amt > 0:
            out[f["group"]] = _r2(out.get(f["group"], 0.0) + amt)
    return out


def with_planned_lines(budget: dict, planned: dict) -> dict:
    """The budget with each month's planned spend folded into its lines (#183): a Group
    with a line gets the amount added (expense lines are negative), a Group without one gets
    a `planned` line — derived for the report, never written to the stored budget. So a
    planned vet visit is budgeted, Budget-vs-Actual judges it, and the unbudgeted prompt
    stays quiet."""
    if not planned:
        return budget
    lines = [dict(l) for l in budget.get("lines") or []]
    by_group = {(l.get("group") or "").strip(): l for l in lines}
    for group, amt in planned.items():
        line = by_group.get(group)
        if line is None:
            lines.append({"group": group, "amount": -amt, "source": "planned", "dataPoints": 0})
        else:
            line["amount"] = _r2(float(line.get("amount") or 0) - amt)
    return {**budget, "lines": lines}


def budget_report(ym: str, today: datetime | None = None) -> dict | None:
    """The month's budget with Budget-vs-Actual rows (each carrying `pill` and absolute
    `budget_abs` / `actual_abs` / `over` for display, and `planned` when planned spend is
    folded into the line) and the expense-side totals the Spend tile compares against.
    None when the month has no budget."""
    budget = budget_for_month(ym)
    if budget is None:
        return None
    planned = planned_by_group(ym, today)
    rows = engine.build_report(with_planned_lines(budget, planned))
    for r in rows:
        r["budget_abs"] = abs(r["budget_amount"])
        r["actual_abs"] = abs(r["actual_amount"])
        r["over"] = _r2(r["actual_abs"] - r["budget_abs"])        # + = more than planned
        r["planned"] = planned.get(r["group"], 0.0)
        r["pill"] = pill(r)
    expense_rows = [r for r in rows if r["kind"] != "income"]
    return {
        "id": budget["_id"],
        "versionName": budget.get("versionName", ""),
        "status": budget.get("status", "draft"),
        "rows": rows,
        "spend_budget": _r2(sum(r["budget_abs"] for r in expense_rows)),
        "spend_actual": _r2(sum(r["actual_abs"] for r in expense_rows)),
        "on_target": sum(1 for r in rows if r["pill"]["cls"] == "ok"),
        "planned_total": _r2(sum(planned.values())),
    }


# --- month facts ------------------------------------------------------------------------

def _trailing(series: list[dict], ym: str, n: int = SERIES_MONTHS) -> list[dict]:
    """The n calendar months ending at ym, zero-filled where the ledger has no rows."""
    by = {r["month"]: r for r in series}
    months = []
    cur = ym
    for _ in range(n):
        months.append(cur)
        cur = prev_month(cur)
    months.reverse()
    return [by.get(m) or {"month": m, "income": 0.0, "expense": 0.0, "net": 0.0} for m in months]


def month_facts(ym: str, today: datetime | None = None) -> dict:
    """Everything the Month page shows for one month; the Notebook and Planner reuse it."""
    today = today or datetime.now(UTC)
    income, expense = rollup.income_expense(month=ym)
    net = _r2(income - expense)
    cfg = savings.get_savings_config()
    series12 = _trailing(rollup.monthly_income_expense(), ym)
    present = [r for r in series12 if r["income"] or r["expense"]]
    budget = budget_report(ym)
    return {
        "month": ym,
        "label": month_label(ym),
        "days": days_in(ym),
        "is_current": ym == today.strftime("%Y-%m"),
        "prev": prev_month(ym),
        "next": next_month(ym),
        "income": _r2(income),
        "expense": _r2(expense),
        "net": net,
        "savings_rate": round(net / income, 4) if income > 0 else None,
        "target_rate": cfg["target_rate"],
        "avg_income_12": _r2(sum(r["income"] for r in present) / len(present)) if present else 0.0,
        "avg_expense_12": _r2(sum(r["expense"] for r in present) / len(present)) if present else 0.0,
        "avg_net_12": _r2(sum(r["net"] for r in present) / len(present)) if present else 0.0,
        "budget": budget,
        "net_worth": networth.net_worth_delta(ym),
        "months12": [r["month"] for r in series12],
        "net12": [r["net"] for r in series12],
        "uncategorized": transactions.count_blank(),
        "income_sources": income_table(ym, today),
        "estimates": ["income_sources"],
    }


# --- income expected vs received ---------------------------------------------------------

def _expected_in_month(series: dict, ym: str) -> float | None:
    """Expected amount from one series in month ym: its amount × the occurrences due that
    month, stepped by the series' origin (expected_flows.occurrences_in_month). A `once`
    flow counts in the month of its anchor and nowhere else; None only for an irregular
    series, which has no period and no date."""
    if series.get("cadence") != "once" and not series.get("period_days"):
        return None
    return round(series["amount"] * expected_flows.occurrences_in_month(series, ym), 2)


def income_table(ym: str, today: datetime | None = None) -> dict:
    """{rows, expected_total, received_total}: one row per recurring income source
    (estimated from the ledger) with what the month expected and received, then a row per
    Category that received income this month without a series ("one-off", nothing expected),
    so the received column adds up to the month's categorised income. A series with nothing
    expected and nothing received in the month (it began later, or is irregular and silent)
    is left out."""
    today = today or datetime.now(UTC)
    received = {r["name"]: r["total"]
                for r in rollup.totals_by("Category", month=ym, where={"Type": "Income"})
                if r["name"]}
    rows = []
    for s in expected_flows.merged_sources(today):
        expected = _expected_in_month(s, ym)
        got = _r2(received.pop(s["category"], 0.0)) if s.get("category") else 0.0
        if not expected and not got:
            continue                                  # nothing to say about this month
        rows.append({
            "source": s["label"], "cadence": s["cadence"], "expected": expected,
            "received": got, "next": s["next_date"], "confidence": s["confidence"],
            "origin": s["origin"],
        })
    for name, total in sorted(received.items(), key=lambda kv: -kv[1]):
        if total:
            rows.append({"source": name, "cadence": "one-off", "expected": None,
                         "received": _r2(total), "next": None, "confidence": None,
                         "origin": "one-off"})
    return {
        "rows": rows,
        "expected_total": _r2(sum(r["expected"] or 0 for r in rows)),
        "received_total": _r2(sum(r["received"] for r in rows)),
    }


# --- frozen figures --------------------------------------------------------------------

def _misses(budget: dict | None) -> list[dict]:
    """The biggest unfavourable expense rows vs budget, most over first (top MISSES)."""
    if not budget:
        return []
    rows = [r for r in budget["rows"] if r["kind"] != "income" and r["over"] > 0]
    rows.sort(key=lambda r: -r["over"])
    return [{"group": r["group"], "budget": r["budget_abs"], "actual": r["actual_abs"],
             "over": r["over"]} for r in rows[:MISSES]]


def figures_from_facts(facts: dict) -> dict:
    """The month figures a Journal entry freezes (D1): what the entry's author saw."""
    nw = facts.get("net_worth") or {}
    budget = facts.get("budget")
    return {
        "period": facts["month"],
        "income": facts["income"], "expense": facts["expense"], "net": facts["net"],
        "savings_rate": facts["savings_rate"],
        "net_worth": nw.get("value"), "net_worth_delta": nw.get("delta"),
        "net_worth_as_of": nw.get("as_of"),
        "budget_version": budget["versionName"] if budget else None,
        "budget_total": budget["spend_budget"] if budget else None,
        "actual_total": budget["spend_actual"] if budget else None,
        "misses": _misses(budget),
        "months12": facts["months12"], "net12": facts["net12"],
    }


def year_figures(year: str) -> dict:
    """A year review's figures: the year's totals, net ÷ income, net worth as of December,
    and the twelve calendar months' net. No budget keys — budgets are monthly."""
    months = [r for r in rollup.monthly_income_expense() if r["month"].startswith(year)]
    by = {r["month"]: r for r in months}
    labels = [f"{year}-{m:02d}" for m in range(1, 13)]
    income = _r2(sum(r["income"] for r in months))
    expense = _r2(sum(r["expense"] for r in months))
    nw = networth.net_worth_delta(f"{year}-12") or {}
    return {
        "period": year,
        "income": income, "expense": expense, "net": _r2(income - expense),
        "savings_rate": round((income - expense) / income, 4) if income > 0 else None,
        "net_worth": nw.get("value"), "net_worth_delta": nw.get("delta"),
        "net_worth_as_of": nw.get("as_of"),
        "budget_version": None, "budget_total": None, "actual_total": None, "misses": [],
        "months12": labels, "net12": [by[m]["net"] if m in by else 0.0 for m in labels],
    }


def figures_for(period: str, today: datetime | None = None) -> dict:
    """Fresh figures for a period, stamped with the freeze time."""
    if is_month(period):
        fig = figures_from_facts(month_facts(period, today))
    elif is_year(period):
        fig = year_figures(period)
    else:
        raise DomainError("period must be YYYY-MM or YYYY")
    return {**fig, "frozen_at": (today or datetime.now(UTC)).isoformat(timespec="seconds")}


# --- journal entries ------------------------------------------------------------------

def _check_period(period: str) -> None:
    if not is_period(period):
        raise DomainError("period must be YYYY-MM or YYYY", status=400)


def is_open(period: str, today: datetime | None = None) -> bool:
    """Whether the period is still running: the current (or a later) month, or the current
    (or a later) year. An open period's figures stay live (ADR-0021, amended 2026-10-14)."""
    today = today or datetime.now(UTC)
    return period >= today.strftime("%Y-%m" if is_month(period) else "%Y")


def _present(entry: dict | None, today: datetime | None) -> dict | None:
    """An entry as the pages read it: figures frozen while the period was still open (rows
    from before the amendment) are not shown — the live ones are, until a save clears them."""
    if entry and entry.get("figures") and is_open(entry["period"], today):
        return {**entry, "figures": None, "frozen_at": None}
    return entry


def get_entry(period: str, today: datetime | None = None) -> dict | None:
    _check_period(period)
    return _present(journal_entries.for_period(period), today)


def save_entry(period: str, body: str, today: datetime | None = None) -> dict:
    """Upsert the body. While the period is open the figures stay live; the first save
    after it ends freezes them (D1), and later saves keep them — only refreeze() replaces
    what the author saw when they wrote. A row frozen while its period was still open
    (before the amendment) goes back to live on its next save."""
    _check_period(period)
    if not isinstance(body, str):
        raise DomainError("body must be text")
    if len(body) > BODY_LIMIT:
        raise DomainError("body is too long")
    existing = journal_entries.for_period(period)
    open_ = is_open(period, today)
    if existing is None:
        figures = None if open_ else figures_for(period, today)
        journal_entries.insert({"period": period, "body": body, "figures": figures,
                                      "frozen_at": figures["frozen_at"] if figures else None})
    else:
        updates = {"body": body}
        if open_ and existing.get("figures"):
            updates.update(figures=None, frozen_at=None)
        elif not open_ and not existing.get("figures"):
            figures = figures_for(period, today)
            updates.update(figures=figures, frozen_at=figures["frozen_at"])
        journal_entries.update(existing["_id"], updates)
    return get_entry(period, today)


def refreeze(period: str, today: datetime | None = None) -> dict:
    """Recompute the frozen figures for an existing entry of a closed period."""
    entry = get_entry(period, today)
    if entry is None:
        raise DomainError("no entry for that period", status=404)
    if is_open(period, today):
        raise DomainError("the figures stay live while the period is open", status=409)
    figures = figures_for(period, today)
    journal_entries.update(entry["_id"], {"figures": figures, "frozen_at": figures["frozen_at"]})
    return get_entry(period, today)


def delete_entry(period: str) -> dict:
    """Audited hard delete (ADR-0005): the row goes to `deletions` first."""
    entry = get_entry(period)
    if entry is None:
        raise DomainError("no entry for that period", status=404)
    deletions.log(journal_entries.table, [entry])
    journal_entries.delete(entry["_id"])
    return {"ok": True, "period": period}


# --- prompts from the data (D8) -----------------------------------------------------------

def _dollars(v) -> str:
    return f"${abs(float(v or 0)):,.0f}"


def prompts(facts: dict, prior_reports: list[dict | None] = ()) -> list[dict]:
    """Sentences the rules derive from a month's facts, as [{id, text}]: an unbudgeted
    expense group (at or above UNBUDGETED_FLOOR), a line at least OVER_PCT over budget, a
    group over budget STREAK months running (`prior_reports` are budget_report() results
    for the preceding months, newest first), a budget line with no activity (finished months
    only — a month that has just begun has not had its chance), the month's net worth change
    (when measured in this month), and a count of uncategorized rows."""
    out = []
    budget = facts.get("budget")
    finished = not facts.get("is_current")
    if budget:
        for r in budget["rows"]:
            if r["kind"] == "income":
                continue
            g = r["group"]
            if r["match"] == "actual_only" and r["actual_abs"] >= UNBUDGETED_FLOOR:
                out.append({"id": f"unbudgeted:{g}",
                            "text": f"{g} spent {_dollars(r['actual_abs'])} with no budget line."})
            elif r["match"] == "both" and r["budget_abs"] > 0 and r["over"] / r["budget_abs"] >= OVER_PCT:
                pct = round(r["over"] / r["budget_abs"] * 100)
                out.append({"id": f"over:{g}",
                            "text": f"{g} ran {pct}% over: {_dollars(r['actual_abs'])} vs {_dollars(r['budget_abs'])}."})
            elif r["match"] == "budget_only" and r["budget_abs"] > 0 and finished:
                out.append({"id": f"idle:{g}",
                            "text": f"{g} had a {_dollars(r['budget_abs'])} line and no activity."})
        priors = list(prior_reports)[:STREAK - 1]
        if len(priors) == STREAK - 1 and all(priors):
            over_before = [{r["group"] for r in p["rows"] if r["kind"] != "income" and r["match"] == "both" and r["over"] > 0}
                           for p in priors]
            for r in budget["rows"]:
                if r["kind"] != "income" and r["match"] == "both" and r["over"] > 0 \
                        and all(r["group"] in s for s in over_before):
                    out.append({"id": f"streak:{r['group']}",
                                "text": f"{r['group']} over budget {STREAK} months running."})
    nw = facts.get("net_worth")
    if nw and nw.get("delta") is not None and nw.get("exact"):
        sign = "+" if nw["delta"] >= 0 else "−"
        out.append({"id": "networth",
                    "text": f"Net worth {sign}{_dollars(nw['delta'])} this month to {_dollars(nw['value'])}."})
    n = facts.get("uncategorized") or 0
    if n:
        out.append({"id": "uncategorized",
                    "text": f"{n} transaction{'s are' if n != 1 else ' is'} still uncategorized."})
    return out


def _squash(text: str) -> str:
    return " ".join((text or "").split())


def addressed(prompt_list: list[dict], body: str) -> list[dict]:
    """Each prompt with `addressed`: True when its sentence occurs in the body (whitespace
    folded). The body is the only record; nothing else marks a prompt done."""
    flat = _squash(body)
    return [{**p, "addressed": _squash(p["text"]) in flat} for p in prompt_list]


def month_prompts(facts: dict, body: str = "") -> list[dict]:
    """The Month page's prompts for `facts`, with the streak rule fed by the two prior
    months' budget reports and `addressed` judged against the entry body."""
    ym = facts["month"]
    priors = []
    for _ in range(STREAK - 1):
        ym = prev_month(ym)
        priors.append(budget_report(ym))
    return addressed(prompts(facts, priors), body)


# --- Notebook page (D7) ---------------------------------------------------------------------

RAIL_MONTHS = 24
_MARKER = re.compile(r"^\s*\[\[(figures|misses)\]\]\s*$")


def notebook_blocks(body: str, figures: dict) -> list[tuple[str, object]]:
    """The Notebook's document as blocks: ("html", rendered Markdown) chunks of the body,
    split at marker lines `[[figures]]` and `[[misses]]` which become ("figures", figures)
    and ("misses", figures["misses"]) blocks (Figure blocks, CONTEXT.md). Without markers
    the figures go before the prose and the misses after (misses only when the figures
    have a budget). An empty body is just the figure blocks."""
    blocks: list[tuple[str, object]] = []
    chunk: list[str] = []
    seen: set[str] = set()

    def flush():
        text = "\n".join(chunk).strip()
        if text:
            blocks.append(("html", documents.render_markdown(text)))
        chunk.clear()

    for line in (body or "").splitlines():
        m = _MARKER.match(line)
        if m:
            flush()
            kind = m.group(1)
            seen.add(kind)
            blocks.append((kind, figures if kind == "figures" else list(figures.get("misses") or [])))
        else:
            chunk.append(line)
    flush()
    if "figures" not in seen:
        blocks.insert(0, ("figures", figures))
    if "misses" not in seen and figures.get("budget_version"):
        blocks.append(("misses", list(figures.get("misses") or [])))
    return blocks


def sparkline(values: list[float], w: int = 180, h: int = 44, pad: int = 4) -> dict:
    """Points for an inline SVG sparkline of a series: {w, h, line, area, zero_y, last_x,
    last_y}. `line` and `area` are SVG path data; the zero line sits at zero_y."""
    vals = [float(v or 0) for v in values] or [0.0]
    lo, hi = min(0.0, *vals), max(0.0, *vals)
    span = (hi - lo) or 1.0
    n = max(len(vals) - 1, 1)
    x = lambda i: pad + i * (w - 2 * pad) / n
    y = lambda v: h - pad - (v - lo) / span * (h - 2 * pad)
    pts = [f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals)]
    line = "M" + " L".join(pts)
    area = f"{line} L{x(len(vals) - 1):.1f},{y(0):.1f} L{x(0):.1f},{y(0):.1f} Z"
    return {"w": w, "h": h, "line": line, "area": area, "zero_y": round(y(0), 1),
            "last_x": round(x(len(vals) - 1), 1), "last_y": round(y(vals[-1]), 1)}


def notebook_rail(period: str, today: datetime | None = None) -> dict:
    """The Notebook's left rail: the last RAIL_MONTHS months (ending at the current month)
    grouped by year, newest first — each month with its net, a `written` flag from the
    journal, and `current` when it is the page's period; each year header carries the same
    flags for its year review. Years in the ledger older than the rail are listed as
    headers only. `max_net` scales the net bars."""
    today = today or datetime.now(UTC)
    nets = {r["month"]: r["net"] for r in rollup.monthly_income_expense()}
    written = journal_entries.periods_written()
    months = []
    ym = today.strftime("%Y-%m")
    for _ in range(RAIL_MONTHS):
        months.append({"month": ym, "label": calendar.month_abbr[int(ym[5:7])], "year": ym[:4],
                       "net": _r2(nets.get(ym, 0.0)), "written": ym in written,
                       "current": ym == period})
        ym = prev_month(ym)
    years = {m["year"] for m in months} | {str(y) for y in rollup.years()} | {today.strftime("%Y")}
    groups = []
    for year in sorted(years, reverse=True):
        groups.append({"year": year, "written": year in written, "current": year == period,
                       "months": [m for m in months if m["year"] == year]})
    return {"groups": groups, "max_net": max([abs(m["net"]) for m in months] + [1.0])}


def notebook_view(period: str, today: datetime | None = None) -> dict:
    """Everything the Notebook page renders for a month or a year period: the entry (or
    none), the figures it shows (frozen when an entry exists, else live), the document
    blocks, the open prompts (months only), the rail and the sparkline."""
    _check_period(period)
    today = today or datetime.now(UTC)
    entry = get_entry(period, today)
    body = (entry or {}).get("body") or ""
    if is_month(period):
        facts = month_facts(period, today)
        live = figures_from_facts(facts)
        prompt_list = month_prompts(facts, body)
        kind, title = "month", month_label(period)
        prev_, next_ = prev_month(period), next_month(period)
    else:
        live = year_figures(period)
        prompt_list = []
        kind, title = "year", f"{period} in review"
        prev_, next_ = str(int(period) - 1), str(int(period) + 1)
    frozen = bool(entry and entry.get("figures"))
    figures = entry["figures"] if frozen else live
    return {
        "period": period, "kind": kind, "title": title, "prev": prev_, "next": next_,
        "entry": entry, "body": body, "figures": figures, "frozen": frozen,
        "open": is_open(period, today),
        "blocks": notebook_blocks(body, figures),
        "preview_html": documents.render_markdown(body),
        "open_prompts": [p for p in prompt_list if not p["addressed"]],
        "addressed_count": sum(1 for p in prompt_list if p["addressed"]),
        "rail": notebook_rail(period, today),
        "sparkline": sparkline(figures.get("net12") or []),
    }


# --- Planner: the year (slice 8) ------------------------------------------------------------

VARIABLE_WINDOW_DAYS = 90


def variable_daily_spend(today: datetime, bill_series: list[dict] | None = None) -> float:
    """Spend per day that is not a recurring bill: the trailing VARIABLE_WINDOW_DAYS of
    Expense-typed outflow minus what the bill series account for over the same window,
    divided by the days. Estimated from the ledger; never below zero."""
    bill_series = recurring.bills(today) if bill_series is None else bill_series
    end = today.replace(tzinfo=None) if today.tzinfo else today
    start = end - timedelta(days=VARIABLE_WINDOW_DAYS)
    expense = abs(rollup.grand_total(start=start, end=end, where={"Type": "Expense"}))
    bills_in_window = sum((s["per_month"] or 0) * VARIABLE_WINDOW_DAYS / recurring.DAYS_PER_MONTH
                          for s in bill_series)
    linked = reconcile.linked_outflow(start.date(), end.date())    # planned spend already matched (#185)
    return _r2(max(0.0, expense - bills_in_window - linked) / VARIABLE_WINDOW_DAYS)


def expected_month(ym: str, income_series: list[dict], bill_series: list[dict],
                   variable_daily: float) -> dict:
    """What a future month looks like from the recurring series: income from the periodic
    income sources, expense from the periodic bills plus the variable spend for its days."""
    income = sum(_expected_in_month(s, ym) or 0 for s in income_series)
    bills = sum(_expected_in_month(s, ym) or 0 for s in bill_series)
    expense = bills + variable_daily * days_in(ym)
    return {"month": ym, "income": _r2(income), "expense": _r2(expense),
            "net": _r2(income - expense), "kind": "expected"}


def year_facts(year: str, today: datetime | None = None) -> dict:
    """Everything the Planner page shows for one year: the twelve months (actual, the
    current month as partial, the rest expected from the recurring series), expected income
    per source against what the year has received, the sinking funds, and the totals."""
    today = today or datetime.now(UTC)
    current = today.strftime("%Y-%m")
    income_series = expected_flows.merged_sources(today)
    bill_series = recurring.bills(today)
    variable = variable_daily_spend(today, bill_series)
    actual = {r["month"]: r for r in rollup.monthly_income_expense() if r["month"].startswith(year)}

    months = []
    for m in range(1, 13):
        ym = f"{year}-{m:02d}"
        if ym > current:
            months.append(expected_month(ym, income_series, bill_series, variable))
        else:
            r = actual.get(ym) or {"income": 0.0, "expense": 0.0, "net": 0.0}
            months.append({"month": ym, "income": _r2(r["income"]), "expense": _r2(r["expense"]),
                           "net": _r2(r["net"]), "kind": "partial" if ym == current else "actual"})

    received = {r["name"]: r["total"]
                for r in rollup.totals_by("Category", year=int(year), where={"Type": "Income"})
                if r["name"]}
    sources = []
    for s in income_series:
        expected_year = _r2(sum(_expected_in_month(s, f"{year}-{m:02d}") or 0 for m in range(1, 13))) \
            if (s.get("period_days") or s.get("cadence") == "once") else None
        got = _r2(received.pop(s["category"], 0.0)) if s.get("category") else 0.0
        if not expected_year and not got:
            continue
        sources.append({"source": s["label"], "cadence": s["cadence"], "expected_year": expected_year,
                        "received_ytd": got,
                        "remaining": _r2(max(0.0, expected_year - got)) if expected_year else None,
                        "next": s["next_date"], "origin": s["origin"]})
    for name, total in sorted(received.items(), key=lambda kv: -kv[1]):
        if total:
            sources.append({"source": name, "cadence": "one-off", "expected_year": None,
                            "received_ytd": _r2(total), "remaining": None, "next": None,
                            "origin": "one-off"})

    cfg = savings.get_savings_config()
    funds = savings.list_goals(int(year), cfg)
    done = [x for x in months if x["kind"] != "expected"]
    return {
        "year": year, "prev": str(int(year) - 1), "next": str(int(year) + 1),
        "current_month": current, "is_current_year": current.startswith(year),
        "months": months,
        "max_bar": max([1.0] + [max(x["income"], x["expense"]) for x in months]),
        "expected_income": sources,
        "expected_total": _r2(sum(s["expected_year"] or 0 for s in sources)),
        "received_total": _r2(sum(s["received_ytd"] for s in sources)),
        "remaining_total": _r2(sum(s["remaining"] or 0 for s in sources)),
        "funds": funds,
        "variable_daily": variable,
        "totals": {
            "income_ytd": _r2(sum(x["income"] for x in done)),
            "expense_ytd": _r2(sum(x["expense"] for x in done)),
            "net_ytd": _r2(sum(x["net"] for x in done)),
            "net_projected": _r2(sum(x["net"] for x in months)),
        },
        "estimates": ["months.expected", "expected_income", "variable_daily"],
    }


# --- Checking forecast (D6, slice 9) --------------------------------------------------------

FORECAST_DAYS = 90
FORECAST_MAX_DAYS = 366
CHECKING = "Checking Account"


def checking_accounts() -> list[dict]:
    """The accounts the forecast starts from: Category or Account Type "Checking Account",
    not Closed, not hidden. [{name, balance}] by name."""
    out = []
    for a in accounts.list(order=[("Account", "asc")]):
        if a.get("is_hidden") or (a.get("Status") or "").strip().lower() == "closed":
            continue
        if CHECKING not in ((a.get("Category") or ""), (a.get("Account Type") or "")):
            continue
        out.append({"name": a.get("Account") or a.get("Account ID") or "?",
                    "balance": _r2(a.get("Amount") or 0)})
    return out


def project(start_balance: float, start: date, days: int, income_series: list[dict],
            bill_series: list[dict], variable_daily: float,
            planned_series: list[dict] = ()) -> dict:
    """Pure: a daily balance from `start` over `days`, each day minus the variable spend
    and plus that day's recurring events and planned spend. {series, events, low,
    end_balance}."""
    end = start + timedelta(days=days)
    due: dict[date, list[dict]] = {}
    for s in income_series:
        for d in expected_flows.due_dates(s, start, end):
            due.setdefault(d, []).append({"label": s["label"], "amount": _r2(s["amount"])})
    for s in bill_series:
        for d in expected_flows.due_dates(s, start, end):
            due.setdefault(d, []).append({"label": s["label"], "amount": _r2(-s["amount"])})
    for s in planned_series:
        if not s.get("placed"):
            continue
        for d in expected_flows.due_dates(s, start, end):
            due.setdefault(d, []).append({"label": s["label"], "amount": _r2(-s["amount"]), "planned": True})

    balance = _r2(start_balance)
    series = [{"date": start.isoformat(), "balance": balance}]
    events = []
    low = {"date": start.isoformat(), "balance": balance}
    for i in range(1, days + 1):
        day = start + timedelta(days=i)
        balance = _r2(balance - variable_daily)
        for ev in sorted(due.get(day, []), key=lambda e: -e["amount"]):      # income first
            balance = _r2(balance + ev["amount"])
            events.append({"date": day.isoformat(), **ev, "balance_after": balance})
        series.append({"date": day.isoformat(), "balance": balance})
        if balance < low["balance"]:
            low = {"date": day.isoformat(), "balance": balance}
    return {"series": series, "events": events, "low": low, "end_balance": balance}


def forecast(today: datetime | None = None, days: int = FORECAST_DAYS) -> dict:
    """The checking forecast: the checking accounts' current amounts carried forward with
    the recurring income and bills and the variable daily spend. Estimated from the ledger."""
    if not 1 <= days <= FORECAST_MAX_DAYS:
        raise DomainError(f"days must be 1–{FORECAST_MAX_DAYS}")
    today = today or datetime.now(UTC)
    start = today.date()
    accts = checking_accounts()
    income_series = expected_flows.merged_sources(today)
    bill_series = recurring.bills(today)
    planned = expected_flows.planned_spend(today)
    variable = variable_daily_spend(today, bill_series)
    start_balance = _r2(sum(a["balance"] for a in accts))
    return {
        "start": start.isoformat(), "days": days,
        "start_balance": start_balance, "accounts": [a["name"] for a in accts],
        "daily_variable": variable,
        **project(start_balance, start, days, income_series, bill_series, variable, planned),
        "estimated": True,
    }


# --- Year plan (ADR-0023, slice 4) ------------------------------------------------------------

WINDOW_MONTHS = 12


def plan_months(today: datetime | date | None = None, start: str | None = None) -> list[str]:
    """The window: WINDOW_MONTHS calendar months starting with the current one, or with
    `start` (YYYY-MM) when the person moves the window (#184)."""
    today = today or datetime.now(UTC)
    ym = start if is_month(start) else today.strftime("%Y-%m")
    out = []
    for _ in range(WINDOW_MONTHS):
        out.append(ym)
        ym = next_month(ym)
    return out


def base_month(ym: str, income_series: list[dict], bill_series: list[dict],
               variable_daily: float, target_rate: float) -> dict:
    """A month before planned spend (D3): expected income, recurring bills, the variable
    spend for its days, the savings contribution (target rate × income), and the base net."""
    income = _r2(sum(_expected_in_month(s, ym) or 0 for s in income_series))
    bills = _r2(sum(_expected_in_month(s, ym) or 0 for s in bill_series))
    variable = _r2(variable_daily * days_in(ym))
    savings_amt = _r2(income * (target_rate or 0))
    return {"month": ym, "label": month_label(ym), "income": income, "bills": bills,
            "variable": variable, "savings": savings_amt,
            "base_net": _r2(income - bills - variable - savings_amt)}


def funding(amount: float, goal: dict | None, index: int, earlier_earmarked: float = 0.0) -> dict | None:
    """How much of `amount` the goal covers by window month `index` (D4): its pooled
    balance now plus its monthly contribution for the months until, less what earlier items
    on the same goal already claim. None without a goal."""
    if not goal:
        return None
    avail = max(0.0, float(goal.get("current_balance") or 0)
                + float(goal.get("monthly_contribution") or 0) * (index + 1) - earlier_earmarked)
    covered = min(amount, avail)
    return {"goal_id": goal["id"], "goal": goal["name"], "covered": _r2(covered),
            "pct": round(min(1.0, avail / amount), 4) if amount > 0 else 1.0,
            "short": _r2(max(0.0, amount - avail))}


def year_plan(today: datetime | None = None, start: str | None = None) -> dict:
    """Everything the Year plan, Projected P&L and Calendar pages show: the window's
    months with base figures, planned items, net and flag; the shelf of unplaced items;
    items dated earlier than the window; the funds panel; the groups for the form."""
    today = today or datetime.now(UTC)
    months = plan_months(today, start)
    current = today.strftime("%Y-%m")
    income_series = expected_flows.merged_sources(today)
    bill_series = recurring.bills(today)
    variable = variable_daily_spend(today, bill_series)
    cfg = savings.get_savings_config()
    goals = {g["id"]: g for g in savings.list_goals(today.year, cfg)}
    flows = expected_flows.planned_spend(today)

    earmarked: dict[str, float] = {}
    out_months = []
    for i, ym in enumerate(months):
        base = base_month(ym, income_series, bill_series, variable, cfg["target_rate"])
        items = []
        for f in flows:
            amt = expected_flows.planned_in_month(f, ym) if f["placed"] else 0.0
            if amt <= 0:
                continue
            goal = goals.get(f["goal_id"]) if f.get("goal_id") else None
            fund = funding(amt, goal, i, earmarked.get(f["goal_id"], 0.0)) if goal else None
            if goal:
                earmarked[goal["id"]] = earmarked.get(goal["id"], 0.0) + amt
            items.append({"id": f["id"], "name": f["label"], "group": f["group"], "amount": amt,
                          "cadence": f["cadence"], "origin": f["origin"], "external_id": f["external_id"],
                          "external_status": f["external_status"],
                          "goal_id": f["goal_id"], "funding": fund, "day_known": f["day_known"],
                          "anchor_date": f["anchor_date"], "notes": f["notes"]})
        items.sort(key=lambda it: (-it["amount"], it["name"]))
        planned = _r2(sum(it["amount"] for it in items))
        net = _r2(base["base_net"] - planned)
        out_months.append({**base, "kind": "past" if ym < current else "partial" if ym == current else "expected",
                           "items": items, "planned": planned, "net": net, "flag": net < 0})

    def brief(f):
        return {"id": f["id"], "name": f["label"], "group": f["group"], "amount": f["amount"],
                "cadence": f["cadence"], "origin": f["origin"], "external_id": f["external_id"],
                "external_status": f["external_status"],
                "goal_id": f["goal_id"], "anchor_date": f["anchor_date"], "month": f["month"],
                "day_known": f["day_known"], "notes": f["notes"]}
    shelf = sorted((brief(f) for f in flows if not f["placed"]),
                   key=lambda b: (b["external_status"] == "researching", -b["amount"], b["name"]))   # decided first
    past = [brief(f) for f in flows if f["placed"] and f["cadence"] == "once" and f["month"] < months[0]]

    funds = []
    for g in goals.values():
        have = float(g.get("current_balance") or 0)
        per = float(g.get("monthly_contribution") or 0)
        by_end = _r2(have + per * WINDOW_MONTHS)
        ear = _r2(earmarked.get(g["id"], 0.0))
        funds.append({"id": g["id"], "name": g["name"], "have": _r2(have), "per": _r2(per),
                      "source": g.get("balance_source", "pooled"), "account": g.get("balance_account"),
                      "earmarked": ear, "by_end": by_end, "short": ear > by_end,
                      "target_amount": g.get("target_amount"), "target_date": g.get("target_date")})

    groups = sorted({f["group"] for f in flows if f["group"]} | set(engine.all_groups()))
    last = sync_runs.recent("future-purchases", limit=1)
    return {
        "start": months[0], "end": months[-1], "months": out_months,
        "current_month": current,
        "window": {"earlier": prev_month(months[0]), "later": next_month(months[0]),
                   "moved": months[0] != current},
        "shelf": shelf, "past": past, "funds": funds, "groups": groups,
        "goals": [{"id": g["id"], "name": g["name"]} for g in goals.values()],
        "cadences": list(expected_flows.CADENCES),
        "totals": {"planned": _r2(sum(m["planned"] for m in out_months)),
                   "flagged": [m["month"] for m in out_months if m["flag"]],
                   "unplaced": len(shelf), "past": len(past)},
        "last_pull": last[0] if last else None,
        "pull_configured": bool(FUTURE_PURCHASES_URL),
        "variable_daily": variable, "target_rate": cfg["target_rate"],
        "estimates": ["income", "bills", "variable", "savings"],
    }


# --- Projected P&L (slice 6) ----------------------------------------------------------------

PNL_SECTIONS = ["Income", "Spend", "Planned", "Savings"]


def projected_pnl(today: datetime | None = None, start: str | None = None) -> dict:
    """The P&L continued past the ledger (ADR-0023 D6): the current month as an actual
    column, then eleven projected ones, tabulated with app.pivot over month-key columns.
    Income sources, Recurring bills, Variable spend, one Planned row per Group with a placed
    item in the window, the Savings contribution, and net after savings per column. The
    projected columns' nets equal year_plan()'s; the actual column reads the ledger: income
    from the rollup, bills as the series expect, variable = actual expense − bills (never
    below zero), savings = the target rate × actual income."""
    today = today or datetime.now(UTC)
    plan = year_plan(today, start)
    months = plan["months"]
    columns = [m["month"] for m in months]
    col_kind = {c: ("actual" if i == 0 else "projected") for i, c in enumerate(columns)}

    cur = months[0]
    actual_income, actual_expense = rollup.income_expense(month=cur["month"])
    actual = {
        "income": _r2(actual_income),
        "bills": cur["bills"],
        "variable": _r2(max(0.0, actual_expense - cur["bills"])),
        "savings": _r2(actual_income * (plan["target_rate"] or 0)),
    }

    def series(key: str) -> dict:
        return {m["month"]: (actual[key] if i == 0 else m[key]) for i, m in enumerate(months)}

    planned_groups: dict[str, dict] = {}
    for m in months:
        for it in m["items"]:
            g = it["group"] or "Planned"
            planned_groups.setdefault(g, {})
            planned_groups[g][m["month"]] = _r2(planned_groups[g].get(m["month"], 0.0) + it["amount"])

    rows = [
        {"section": "Income", "label": "Income sources", "by_col": series("income")},
        {"section": "Spend", "label": "Recurring bills", "by_col": series("bills")},
        {"section": "Spend", "label": "Variable spend", "by_col": series("variable")},
        *[{"section": "Planned", "label": f"Planned · {g}", "group": g, "by_col": by}
          for g, by in sorted(planned_groups.items())],
        {"section": "Savings", "label": "Savings contribution", "by_col": series("savings")},
    ]
    for r in rows:
        r["total"] = _r2(sum(r["by_col"].get(c, 0.0) for c in columns))
    table = pivot(rows, columns, section_of=lambda r: r["section"], values_of=lambda r: r["by_col"],
                  sort_of=lambda r: r["total"], section_order=PNL_SECTIONS)

    def sub(label: str) -> dict:
        s = next((x for x in table["sections"] if x["label"] == label), None)
        return s["subtotals"] if s else {c: 0.0 for c in columns}
    inc, spend, planned, sav = sub("Income"), sub("Spend"), sub("Planned"), sub("Savings")
    net = {c: _r2(inc[c] - spend[c] - planned[c] - sav[c]) for c in columns}
    return {
        "columns": columns, "col_kind": col_kind,
        "labels": {c: f"{calendar.month_abbr[int(c[5:7])]} {c[2:4]}" for c in columns},
        "table": table,
        "net": {"by_col": net, "total": _r2(sum(net.values()))},
        "flags": [c for c in columns if net[c] < 0],
        "year_plan": plan,
    }
