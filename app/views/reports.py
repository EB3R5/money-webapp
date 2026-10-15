"""Reports — server-rendered pivot tables (Jinja), modeled on the existing
Looker P&L / Balance Sheet exports in Finance/Reports. Computed through the shared
cashflow rollup and the balance-history store; render-only here so they print cleanly
to PDF later (WeasyPrint)."""

from datetime import UTC, datetime

from django.urls import path

from .. import networth, rollup, web
from ..card_collection import num0
from ..inventory_sync import sync_inventory_to_balances
from ..pivot import pivot
from ..store.balance_history import balance_history
from ..store.inventory import inventory

def _int(request, name: str, default=None):
    """An optional integer query parameter; anything unparsable is the default."""
    v = request.GET.get(name)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError:
        return default


MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TYPE_ORDER = ["Income", "Transfer", "Expense"]


@web.GET
def pnl(request):
    year = _int(request, "year")
    years = rollup.years()
    if not years:
        return web.page(request, "pnl.html", {"years": [], "year": None, "months": [],
                                              "sections": [], "month_totals": {}, "grand_total": 0})
    now_year = datetime.now(UTC).year
    year = year or (now_year if now_year in years else years[0])

    # cells[(type, group)][m] = amount ; track months present
    cells, months_present = {}, set()
    for r in rollup.totals_by_month(["Type", "Group"], year=year):
        t = r["Type"] or "(none)"
        g = r["Group"] or "(none)"
        m = int(r["month"][5:7])
        cells.setdefault((t, g), {})[m] = r["total"]
        months_present.add(m)

    months = sorted(months_present)

    # One row per (Type, Group), pivoted into Type-ordered sections over the month columns.
    rows = [{"type": t, "group": g, "by_month": by_m, "total": round(sum(by_m.values()), 2)}
            for (t, g), by_m in cells.items()]
    table = pivot(
        rows, columns=months,
        section_of=lambda r: r["type"],
        values_of=lambda r: r["by_month"],
        sort_of=lambda r: r["total"],
        section_order=TYPE_ORDER,
    )
    sections = [{"type": s["label"], "groups": s["rows"],
                 "sub_by_month": s["subtotals"], "subtotal": s["subtotal"]}
                for s in table["sections"]]

    return web.page(request, "pnl.html", {
        "years": years, "year": year,
        "months": months, "month_abbr": MONTH_ABBR,
        "sections": sections, "month_totals": table["totals"],
        "grand_total": table["grand"],
    })


@web.GET
def balance_sheet(request):
    """One month's balance sheet. The month comes as ?year=&month= or as the picker's
    ?ym=YYYY-M (a plain form submit, so it works without an inline handler under the CSP);
    an unknown or missing month falls back to the latest one with Snapshots."""
    year, month, ym = _int(request, "year"), _int(request, "month"), request.GET.get("ym")
    if ym and year is None and month is None:
        try:
            year, month = (int(x) for x in ym.split("-", 1))
        except ValueError:
            year = month = None
    months = balance_history.months()
    if not months:
        return web.page(request, "balance_sheet.html", {"months": [], "sections": []})
    if year is None or month is None or (year, month) not in months:
        year, month = months[0]

    MEASURES = ("starting", "ending", "maxb")
    rows = networth.month_rows(balance_history.in_month(year, month))

    # Pivot accounts into Class-ordered sections; each section subtotals the 3 measures.
    table = pivot(
        rows, columns=list(MEASURES),
        section_of=lambda r: r["cls"],
        values_of=lambda r: {k: r[k] for k in MEASURES},
        sort_of=lambda r: r["ending"],
        section_order=networth.CLASS_ORDER,
    )
    sections = [{"cls": s["label"], "accounts": s["rows"], "subtotal": s["subtotals"]}
                for s in table["sections"]]

    totals = networth.summarize(rows)                        # one owner of the figure
    income, expense = rollup.income_expense(month=f"{year:04d}-{month:02d}")

    return web.page(request, "balance_sheet.html", {
        "months": months, "year": year, "month": month, "month_abbr": MONTH_ABBR,
        "sections": sections,
        "net_worth": totals["net_worth"], "assets": totals["assets"], "liabilities": totals["liabilities"],
        "income": income, "expense": expense, "net_income": round(income - expense, 2),
    })


def _inventory_rollup(docs):
    """Category rollup for the inventory overview.
    Cost = sum(Qty*Unit_Cost); salvage summed raw per item; useful-life averages
    only the rows with a positive value; categories sorted alphabetically."""
    cats = {}
    for doc in docs:
        cat = str(doc.get("Category") or "").strip()
        if not cat:
            continue
        c = cats.setdefault(cat, {"items": 0, "qty": 0.0, "cost": 0.0, "salvage": 0.0, "life": []})
        qty = num0(doc.get("Qty"))
        c["items"] += 1
        c["qty"] += qty
        c["cost"] += qty * num0(doc.get("Unit_Cost"))
        c["salvage"] += num0(doc.get("Salvage_Value"))
        life = num0(doc.get("Useful_Life_Years"))
        if life > 0:
            c["life"].append(life)

    grand_cost = sum(c["cost"] for c in cats.values())
    rows, tot = [], {"items": 0, "qty": 0.0, "cost": 0.0, "salvage": 0.0,
                     "net": 0.0, "life_sum": 0.0, "life_count": 0}
    for cat in sorted(cats):
        c = cats[cat]
        net = round(c["cost"] - c["salvage"], 2)
        rows.append({
            "category": cat, "count": c["items"], "qty": c["qty"],
            "cost": round(c["cost"], 2),
            "avg_unit": round(c["cost"] / c["qty"], 2) if c["qty"] else 0.0,
            "salvage": round(c["salvage"], 2), "net": net,
            "pct": c["cost"] / grand_cost if grand_cost else 0.0,
            "avg_life": round(sum(c["life"]) / len(c["life"]), 1) if c["life"] else 0.0,
        })
        tot["items"] += c["items"]; tot["qty"] += c["qty"]; tot["cost"] += c["cost"]
        tot["salvage"] += c["salvage"]; tot["net"] += net
        tot["life_sum"] += sum(c["life"]); tot["life_count"] += len(c["life"])

    grand = {
        "count": tot["items"], "qty": tot["qty"], "cost": round(tot["cost"], 2),
        "avg_unit": round(tot["cost"] / tot["qty"], 2) if tot["qty"] else 0.0,
        "salvage": round(tot["salvage"], 2), "net": round(tot["net"], 2),
        "pct": 1.0 if grand_cost else 0.0,
        "avg_life": round(tot["life_sum"] / tot["life_count"], 1) if tot["life_count"] else 0.0,
    }
    return rows, grand


@web.GET
def inventory_overview(request):
    rows, grand = _inventory_rollup(inventory.list())
    return web.page(request, "inventory_overview.html", {"rows": rows, "grand": grand})


@web.POST
def inventory_overview_sync(request):
    """Sync Inventory Data — pull the current inventory into balanceHistory as Current
    Asset line items (mapped by category/group/type) so they appear on the balance sheet."""
    rows, _grand = _inventory_rollup(inventory.list())
    return web.json(sync_inventory_to_balances(rows))


urlpatterns = [
    path("pnl", pnl),
    path("balance-sheet", balance_sheet),
    path("inventory-overview", inventory_overview),
    path("api/inventory-overview/sync", inventory_overview_sync),
]
