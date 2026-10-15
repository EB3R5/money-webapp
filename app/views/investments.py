"""Investments — page + endpoints over the current portfolio. Shows holdings with
their (refreshable) live prices and lets you port them into balanceHistory. The data
logic lives in app/investments.py; this is just the HTTP surface."""

from django.urls import path

from .. import web
from ..investments import (open_holdings, portfolio_rows, refresh_prices,
                           sync_portfolio_to_balances, update_holding)


@web.GET
def investments_page(request):
    rows, total = portfolio_rows(open_holdings())
    return web.page(request, "investments.html", {"rows": rows, "total": total})


@web.POST
def investments_refresh(request):
    """Fetch live quotes (yfinance) and rewrite current price/value for each holding."""
    return web.json(refresh_prices())


@web.POST
def investments_holding_update(request, holding_id: str):
    """Edit one holding's position facts (Shares / Purchase Price / Brokerage)."""
    payload, status = update_holding(holding_id, web.read_json(request))
    return web.json(payload, status)


@web.POST
def investments_sync(request):
    """Port the portfolio into balanceHistory as Equity/Asset line items."""
    return web.json(sync_portfolio_to_balances())


# The literal "holding" segment keeps the param route clear of refresh-prices and sync.
urlpatterns = [
    path("investments", investments_page),
    path("api/investments/refresh-prices", investments_refresh),
    path("api/investments/holding/<str:holding_id>", investments_holding_update),
    path("api/investments/sync", investments_sync),
]
