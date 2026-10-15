"""Dashboard — ECharts views driven by the shared cashflow rollup over the transactions store."""

from django.urls import path

from .. import rollup, web


@web.GET
def dashboard_page(request):
    return web.page(request, "dashboard.html", {})


@web.GET
def monthly_net(request):
    """Net cash flow per month (income − expense), classified by transaction Type via the
    shared cashflow rollup so it agrees with the P&L and balance-sheet reports — not the
    sign-of-Amount rule that drifted (bug #2)."""
    series = rollup.monthly_income_expense()
    return web.json({"labels": [r["month"] for r in series],
                     "net": [r["net"] for r in series],
                     "spend": [r["expense"] for r in series],
                     "income": [r["income"] for r in series]})


@web.GET
def by_category(request):
    """Top 12 spending categories (outflows only), via the shared rollup. totals_by sorts
    most-negative first, so the leading rows are the biggest spenders — abs for display."""
    rows = (rollup.totals_by("Category", outflows=True, none_label="(uncategorized)"))[:12]
    return web.json({"categories": [r["name"] for r in rows],
                     "spend": [round(abs(r["total"]), 2) for r in rows]})


urlpatterns = [
    path("dashboard", dashboard_page),
    path("api/dashboard/monthly", monthly_net),
    path("api/dashboard/by-category", by_category),
]
