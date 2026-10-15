"""Pivot — the pure tabulation behind the server-rendered report pivot tables.

The P&L and Balance Sheet reports (app/views/reports.py) each hand-rolled the same
shape: take already-aggregated rows, bucket them into ordered sections along a canonical
dimension order, sort the rows inside each section, and accumulate per-section subtotals,
per-column totals, and a grand total. That tabulation had no interface, so it had no test
surface — the maths was reachable only by rendering a full page against the database.

This module owns it once, as pure functions: aggregated rows in, ordered sections out, no
DB. Each report keeps what is genuinely its own (the SQL aggregation and the label
canonicalization) and hands the tabulation here.
"""

from typing import Callable, Iterable


def ordered(seen: Iterable[str], preferred: Iterable[str]) -> list:
    """Canonical-first ordering: the `preferred` labels that appear in `seen` (in preferred
    order), then any remaining labels (in first-seen order)."""
    seen = list(dict.fromkeys(seen))
    preferred = list(preferred)
    return [k for k in preferred if k in seen] + [k for k in seen if k not in preferred]


def _num(v) -> float:
    return v or 0


def pivot(rows: list, columns: list, *,
          section_of: Callable, values_of: Callable, sort_of: Callable,
          section_order: Iterable[str] = ()) -> dict:
    """Group `rows` into ordered sections with subtotals, column totals, and a grand total.

    rows          — the already-aggregated row objects (dicts), carried through untouched.
    columns       — ordered column keys to subtotal across (months, or fixed measures).
    section_of(r) — the row's section label.
    values_of(r)  — {column: number} for the row; a missing column counts as 0.
    sort_of(r)    — rows within a section sort by |this| descending.
    section_order — canonical leading section order; the rest follow in first-seen order.

    Returns {"sections": [{"label", "rows", "subtotals": {col: n}, "subtotal": n}],
             "totals": {col: n}, "grand": n}. `subtotal` is the row-total sum (== the sum
             of the column subtotals when the columns span the whole row, as for the P&L).
    """
    by_section: dict = {}
    for r in rows:
        by_section.setdefault(section_of(r), []).append(r)

    sections, totals, grand = [], {c: 0.0 for c in columns}, 0.0
    for label in ordered(by_section.keys(), section_order):
        srows = sorted(by_section[label], key=lambda r: abs(sort_of(r)), reverse=True)
        vals = [values_of(r) for r in srows]
        subtotals = {c: round(sum(_num(v.get(c)) for v in vals), 2) for c in columns}
        subtotal = round(sum(round(sum(_num(v.get(c)) for c in columns), 2) for v in vals), 2)
        for c in columns:
            totals[c] = round(totals[c] + subtotals[c], 2)
        grand = round(grand + subtotal, 2)
        sections.append({"label": label, "rows": srows,
                         "subtotals": subtotals, "subtotal": subtotal})
    return {"sections": sections, "totals": totals, "grand": grand}
