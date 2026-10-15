"""Category Insights — a cashflow deep-dive that mirrors the Looker/Data Studio
"Category Insights" report (Cashflow Statement). Three linked panels over the
transactions collection, each a drill-down level of sum(Amount), most-negative first:

    Group totals  →  Category totals  →  individual transactions

with cascading filter controls (date range, Group, Category, description search). The
filters flow downward: the Group panel respects date+search; picking a Group narrows the
Category panel; picking a Category narrows the transaction list. Grand total is the
sum(Amount) over the date+search scope, matching the report (e.g. -8,041 all-time).

Render-only page + one JSON endpoint; the heavy lifting is the shared cashflow rollup
over the transactions store.
"""

from datetime import datetime, timedelta

from django.urls import path

from .. import rollup, web
from ..store.transactions import transactions

NONE_LABEL = "(none)"          # how a null Group/Category is shown + round-tripped
TXN_LIMIT = 500               # cap the detail panel; report paginates, we show the top slice


def _parse_date(s: str | None, end: bool = False):
    """YYYY-MM-DD → naive datetime, or None. `end` pushes to end-of-day so the range is
    inclusive (Dates are stored as naive ISO text)."""
    if not s:
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return d + timedelta(days=1) - timedelta(microseconds=1) if end else d


def _scope(start, end, q, group=None, category=None) -> dict:
    """The rollup scope for one panel. Each downstream panel passes more constraints."""
    where = {}
    if group is not None:
        where["Group"] = None if group == NONE_LABEL else group
    if category is not None:
        where["Category"] = None if category == NONE_LABEL else category
    return {"start": start, "end": end, "like": {"Description": q} if q else None, "where": where}


def _totals(field: str, scope: dict) -> list:
    """[{name, total}] grouped by `field`, via the shared cashflow rollup (report order)."""
    return rollup.totals_by(field, none_label=NONE_LABEL, **scope)


@web.GET
def category_insights_page(request):
    groups = [g for g in transactions.distinct("Group") if g]
    categories = [c for c in transactions.distinct("Category") if c]
    lo, hi = rollup.date_span()
    return web.page(request, "category_insights.html", {
        "groups": groups, "categories": categories,
        "min_date": lo.date().isoformat() if isinstance(lo, datetime) else "",
        "max_date": hi.date().isoformat() if isinstance(hi, datetime) else "",
        "none_label": NONE_LABEL,
    })


@web.GET
def category_insights_data(request):
    g = request.GET.get
    start, end, q, group, category = g("start"), g("end"), g("q"), g("group"), g("category")
    s, e = _parse_date(start), _parse_date(end, end=True)
    q = (q or "").strip() or None
    group = group or None
    category = category or None

    # Cascading scope: groups respect date+q; categories add the group; txns add the category.
    group_scope = _scope(s, e, q)
    cat_scope = _scope(s, e, q, group=group)

    groups = _totals("Group", group_scope)
    categories = _totals("Category", cat_scope)

    grand_total = rollup.grand_total(**group_scope)

    # Transaction detail — most-negative first, capped.
    rows, n = transactions.insights(
        start=s, end=e, text=q, limit=TXN_LIMIT,
        group=(None if group == NONE_LABEL else group) if group is not None else ...,
        category=(None if category == NONE_LABEL else category) if category is not None else ...)
    txns = []
    for d in rows:
        dt = d.get("Date")
        txns.append({
            "date": dt.date().isoformat() if isinstance(dt, datetime) else None,
            "category": d.get("Category") or NONE_LABEL,
            "description": d.get("Description") or "",
            "amount": round(d.get("Amount") or 0, 2),
        })

    return web.json({
        "groups": groups, "categories": categories,
        "transactions": txns, "txn_count": n, "txn_limit": TXN_LIMIT,
        "grand_total": grand_total,
    })


urlpatterns = [
    path("category-insights", category_insights_page),
    path("api/category-insights/data", category_insights_data),
]
