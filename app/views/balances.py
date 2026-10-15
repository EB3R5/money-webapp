"""Balances — the balance_history Grid, same AG Grid datasource as the ledger. Page render
+ a store-backed Grid datasource (Infinite Row Model); the block/row/update/delete dance
lives in app/grid.py. This file declares the columns and keeps the one balances-specific
extra: stamping a fresh Snapshot from an account's current Amount (/api/balances/from-account)."""

import secrets
from datetime import date, datetime

from django.urls import path

from .. import web
from ..grid import Grid
from ..store.accounts import accounts
from ..store.balance_history import balance_history

# Grid columns (keys on the balance_history store). "Account Type" is the granular kind
# (Checking Account, Common Stock); the coarse "Type" stays off the grid.
COLUMNS = ["Date", "Account", "Institution", "Class", "Account Type", "Balance"]

grid = Grid(
    store=balance_history,
    columns=COLUMNS,
    search_keys=["Account", "Institution", "Class"],
    default_sort=[("Date", "desc")],
)


@web.GET
def balances_page(request):
    return web.page(request, "balances.html", {"total": balance_history.count(), "columns": COLUMNS})


# Fields carried from an account onto a fresh snapshot, plus the ones inherited from that
# account's most recent existing Snapshot (institution/class aren't on accounts). Accounts
# created by the type-aware Add flow store a granular "Account Type"; older ones fall back
# to the coarse Type for the grid's column.
_FROM_ACCT = {"Account": "Account", "Account ID": "Account ID", "Type": "Type",
              "Group": "Group", "Category": "Category"}
_INHERIT = ["Institution", "Class"]


@web.POST
def balance_from_account(request, account_id: str):
    """Stamp a new Snapshot from an account's current Amount, dated today. Institution and
    Class are inherited from that account's latest existing Snapshot, by Account ID."""
    acct = accounts.get(account_id)
    if not acct:
        return web.json({"ok": False, "error": "account not found"}, 404)

    doc = {"_id": "man_" + secrets.token_hex(10),
           "Date": datetime.combine(date.today(), datetime.min.time()),
           "Balance": acct.get("Amount"),
           "Account Type": acct.get("Account Type") or acct.get("Type"),
           "_src": "manual"}
    for dst, src in _FROM_ACCT.items():
        doc[dst] = acct.get(src)

    prior = balance_history.latest_for_account(acct.get("Account ID")) if acct.get("Account ID") else None
    if prior:
        for f in _INHERIT:
            doc[f] = prior.get(f)

    balance_history.insert(doc)
    return web.json({"ok": True, "id": doc["_id"], "row": grid.serialize(balance_history.get(doc["_id"]))})


urlpatterns = [
    *grid.urlpatterns("balances"),
    path("balances", balances_page),
    path("api/balances/from-account/<str:account_id>", balance_from_account),
]
