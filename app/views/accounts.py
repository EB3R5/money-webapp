"""Accounts — a CardCollection adapter. Accounts surfaced as clickable cards grouped
by Type; clicking a card opens an editable modal that writes back to the `accounts`
store via /api/accounts/{id}. Only ~54 accounts, so the full set is embedded in
the page.

Add-account is type-aware: pick a launch type (Bank/cash, Credit card, Common stock,
Loan) and the modal shows that type's fields. Saving fans out — detail record
(portfolio holding / credit registry entry) and a first classified balance snapshot
land BEFORE the card, so a failed save never leaves a visible orphan card. The type
preset stamps the balance-sheet classification; the user never types Class/Group on
this form. See docs/plans/2026-07-15-001-feat-dynamic-account-entry-plan.md.
"""

import secrets
from datetime import UTC, datetime

from django.urls import path

from .. import credit, investments, registry, snapshot, web
from ..card_collection import CardCollection, CardField, num0
from ..simplefin import link as feed_link
from ..web import DomainError
from ..store.accounts import accounts
from ..store.balance_history import balance_history
from ..store.credit_accounts import credit_accounts
from ..store.deletions import deletions
from ..store.portfolio import portfolio

CREATE_SRC = "account_create"   # creation snapshots; the portfolio month guard ignores this source
ACCOUNT_PREFIX = "ACC"

# Per-launch-type create config: visible form fields, classification preset (stamped on
# the card and its first snapshot), and which detail collection owns the card's value.
ACCOUNT_TYPES = {
    "Bank/cash": {
        "fields": ["Account", "Institution", "Amount"],
        "preset": {"Type": "Assets", "Group": "Current Assets",
                   "Category": "Checking Account", "Account Type": "Checking Account"},
    },
    "Credit card": {
        "fields": ["Account", "Institution", "Credit Limit", "APR %", "Min Payment",
                   "Annual Fee", "Opened Date", "Opening Balance"],
        "preset": {"Type": "Liabilities", "Group": "Current Liabilities",
                   "Category": "Credit Card Debt", "Account Type": "Credit Card Debt"},
        "linked": "credit",
    },
    "Common stock": {
        "fields": ["Ticker", "Shares", "Purchase Price", "Brokerage"],
        "preset": {"Type": "Equity", "Group": "Stockholder's Equity",
                   "Category": "Common Stock", "Account Type": "Common Stock"},
        "linked": "portfolio",
    },
    "Loan": {
        "fields": ["Account", "Institution", "Balance Owed", "APR %", "Min Payment",
                   "Opened Date"],
        "preset": {"Type": "Liabilities", "Group": "Current Liabilities",
                   "Category": "Loan", "Account Type": "Loan"},
    },
}

# Form-only fields the fan-out consumes; they never persist on the card doc.
TRANSIENT_FIELDS = {"Ticker", "Shares", "Purchase Price", "Brokerage",
                    "Opening Balance", "Balance Owed"}
_ALL_TYPE_FIELDS = {f for t in ACCOUNT_TYPES.values() for f in t["fields"]}

# Fields shown when editing an existing card (create mode shows the type's set instead).
EDIT_FIELDS = ["Account", "Type", "Group", "Category", "Account Type", "Amount", "Status",
               "Institution", "APR %", "Annual Fee", "Credit Limit", "Min Payment",
               "Opened Date", "Age (Last Date)", "Usage Notes"]


def linked_kind(doc) -> str | None:
    """'portfolio' | 'credit' | None — which detail collection owns this card's value."""
    t = ACCOUNT_TYPES.get((doc or {}).get("Account Kind") or "")
    return t.get("linked") if t else None


def _err(msg, code=400):
    return web.json({"ok": False, "error": msg}, code)


def _on_create(doc):
    # Mint the Account ID balance snapshots link on; default new accounts to Active
    # so they show under the default status filter.
    if not doc.get("Account ID"):
        doc["Account ID"] = "MAN-" + secrets.token_hex(4).upper()
    doc.setdefault("Status", "Active")


def _is_closed(row: dict) -> bool:
    return (row.get("Status") or "") == "Closed"


def _card_name_taken(name: str) -> bool:
    return name.lower() in {(a.get("Account") or "").lower()
                            for a in accounts.list() if not _is_closed(a)}


def _holding_conflict(ticker: str):
    """None (free), 'dup', or the stray holding row (linked but its card is gone)."""
    for h in investments.open_holdings():
        if (h.get("Asset") or "").strip().upper() != ticker:
            continue
        acct_id = h.get("account_id")
        if acct_id and not accounts.one({"Account ID": acct_id}):
            return h          # stray from a failed save — replace, don't reject
        return "dup"
    return None


def _credit_conflict(name: str):
    """None (free), 'dup', or the stray registry doc (linked but its card is gone)."""
    for e in credit_accounts.list():
        if (e.get("name") or "").strip().lower() != name.lower():
            continue
        if not credit._is_active(e.get("status")):
            continue          # archived entries don't block re-creation
        acct_id = e.get("account_id")
        if acct_id and not accounts.one({"Account ID": acct_id}):
            return e          # stray from a failed save
        return "dup"
    return None


def _fan_out(doc, body):
    """Validate + fan out one type-aware create: detail record and first classified
    snapshot are written here, BEFORE the card insert (a failure leaves no orphan card).
    Mutates `doc` — pops transient form fields, stamps the classification preset."""
    kind = (doc.get("Account Kind") or "").strip()
    t = ACCOUNT_TYPES.get(kind)
    if not t:
        return _err("choose an account type")

    # Per-type allowlist: a hidden field smuggled into the payload is dropped.
    allowed = set(t["fields"]) | {"Account Kind", "Status", "Usage Notes"}
    for k in list(doc):
        if k in _ALL_TYPE_FIELDS and k not in allowed:
            doc.pop(k)

    preset = t["preset"]
    when = datetime.now(UTC)

    if kind == "Common stock":
        ticker = (doc.pop("Ticker", None) or "").strip().upper()
        if not ticker or investments.normalize_ticker(ticker) is None:
            return _err("Ticker must be a resolvable symbol")
        shares = num0(doc.pop("Shares", None))
        if shares <= 0:
            return _err("Shares must be a positive number")
        purchase = num0(doc.pop("Purchase Price", None))
        if purchase <= 0:
            return _err("Purchase Price must be a positive amount")
        brokerage = (doc.pop("Brokerage", None) or "").strip() or investments.DEFAULT_INSTITUTION
        doc["Account"] = ticker            # the card is named the ticker (page + legacy push key)
        doc.setdefault("Institution", brokerage)
        doc["Amount"] = round(purchase, 2)
        balance = round(purchase, 2)
    else:
        name = (doc.get("Account") or "").strip()
        if not name:
            return _err("Account name is required")
        doc["Account"] = name
        if kind == "Loan":
            owed = num0(doc.pop("Balance Owed", None))
            if owed <= 0:
                return _err("Balance Owed must be a positive amount")
            # A2 verified 2026-07-15: migrated liability snapshots AND cards store
            # positive magnitudes (275/300 rows, 20/27 cards) — new liabilities match.
            doc["Amount"] = abs(round(owed, 2))
            balance = doc["Amount"]
        elif kind == "Credit card":
            opening = num0(doc.pop("Opening Balance", None))
            doc["Amount"] = abs(round(opening, 2))
            balance = doc["Amount"]
        else:  # Bank/cash
            balance = round(num0(doc.get("Amount")), 2)
            doc["Amount"] = balance

    name = doc["Account"]
    if _card_name_taken(name):
        return _err(f'an active account named "{name}" already exists')

    # Detail record first (stock / credit), replacing a stray from a failed prior save.
    if kind == "Common stock":
        conflict = _holding_conflict(name)
        if conflict == "dup":
            return _err(f'an active holding for "{name}" already exists on Investments')
        if conflict is not None:
            deletions.log(portfolio.table, [conflict])
            portfolio.delete(conflict["_id"])
        portfolio.insert({
            "_id": "man_" + secrets.token_hex(10),
            "Asset": name, "Account": doc.get("Institution"),
            "Group": "Equity", "Type": "Individual Stock", "Category": "Common Stock",
            "Shares": shares,
            "Purchase Price": balance,
            "Current Price": round(balance / shares, 4),
            "Current Value": balance,
            "account_id": doc["Account ID"],
        })
    elif kind == "Credit card":
        conflict = _credit_conflict(name)
        if conflict == "dup":
            return _err(f'an active credit entry named "{name}" already exists on Credit')
        if conflict is not None:
            deletions.log(credit_accounts.table, [conflict])
            credit_accounts.delete(conflict["_id"])
        registry.add_doc(credit_accounts, {
            "name": name, "type": "Credit Card",
            "opened_date": doc.get("Opened Date") or None,
            "credit_limit": doc.get("Credit Limit"),
            "apr": credit._rate(doc.get("APR %"), "APR %"),
            "min_payment": doc.get("Min Payment"),
            "annual_fee": doc.get("Annual Fee"),
            "status": "Active",
            "balance_account": name,       # the name-keyed join the Credit page already uses
            "account_id": doc["Account ID"],
        })

    # First classified snapshot — the account is on the balance sheet from day one.
    snap = snapshot.snapshot_doc(
        _id=f"acctcreate_{snapshot.slug(name)}_{int(when.timestamp() * 1_000_000)}",
        account=name, balance=balance,
        category=preset["Category"], group=preset["Group"], type_=preset["Type"],
        account_type=preset["Account Type"], cls=preset["Type"],
        institution=doc.get("Institution"),
        acct_id=doc["Account ID"],
        src=CREATE_SRC, when=when)
    snapshot.append(CREATE_SRC, [snap])

    doc.update(preset)
    return None


# Fields a linked card may still edit — everything else is owned by the detail record.
LINKED_EDITABLE = {"Institution", "Usage Notes", "Age (Last Date)"}


def _page_overlay(docs):
    """Derive-at-read: linked cards display their detail record's value, not a stored
    copy. Stock ← holding's Current Value (by account_id); credit ← newest balance
    snapshot (by Account name — the same join the Credit page uses, so grid-added rows
    with no Account ID still surface). Runs before sectioning: group totals derive too."""
    stock = {d["Account ID"]: d for d in docs if linked_kind(d) == "portfolio"}
    cred = {(d.get("Account") or ""): d for d in docs if linked_kind(d) == "credit"}

    if stock:
        for h in portfolio.list({"account_id": list(stock)}):
            card = stock.get(h.get("account_id"))
            if card:
                card["Amount"] = card["_amount"] = round(num0(h.get("Current Value")), 2)
    if cred:
        latest = balance_history.latest_by_account()
        for name, card in cred.items():
            snap = latest.get(name)
            if snap and snap.get("balance") is not None:
                card["Amount"] = card["_amount"] = round(snap["balance"], 2)


def _before_update(doc_id, update):
    """Type-owned fields on a linked card are read-only — the detail record owns them."""
    doc = accounts.get(doc_id)
    kind = linked_kind(doc)
    if not kind:
        return None
    locked = [k for k in update if k not in LINKED_EDITABLE]
    if locked:
        page = "Investments" if kind == "portfolio" else "Credit"
        return f"{', '.join(locked)} is managed on the {page} page"
    return None


def _accounts_filter(request, row) -> bool:
    """Skip nameless placeholder rows and hidden rows (unlinked feed accounts), and filter
    by status (default hides Closed)."""
    if not row.get("Account") or row.get("is_hidden"):
        return False
    status = request.GET.get("status", "active")
    if status == "active":
        return not _is_closed(row)
    if status == "closed":
        return _is_closed(row)
    return True   # status == "all"


# Feed accounts a person can promote to a card of their own: the kinds without a detail
# record fan-out, plus Credit card (its registry entry is created here, as the Add-account
# flow does). A bank feed never carries a stock.
PROMOTABLE = [k for k in ACCOUNT_TYPES if ACCOUNT_TYPES[k].get("linked") != "portfolio"]


def _feed_banner(request):
    """The unlinked feed strip's context: placeholders, ignored ones, the cards a placeholder
    may link to, and the kinds it may be promoted as. None when there is nothing to show."""
    unlinked, ignored = feed_link.unlinked(), feed_link.ignored()
    if not unlinked and not ignored:
        return None
    cards = [{"_id": a["_id"], "Account": a.get("Account"), "Type": a.get("Type")}
             for a in accounts.list(order=[("Account", "asc")])
             if a.get("Account") and not a.get("is_hidden") and not _is_closed(a)
             and not a.get("simplefin_account_id") and a.get("Account ID")]
    return {"unlinked": unlinked, "ignored": ignored, "cards": cards, "kinds": PROMOTABLE}


def _promote(body: dict) -> dict:
    kind = (body.get("kind") or "").strip()
    if kind not in PROMOTABLE:
        raise DomainError(f"kind must be one of {', '.join(PROMOTABLE)}")
    res = feed_link.promote(body.get("feed_id"), kind, ACCOUNT_TYPES[kind]["preset"])
    if kind == "Credit card":            # the same registry entry the Add-account fan-out writes
        card = accounts.get(res["card"])
        registry.add_doc(credit_accounts, {
            "name": card["Account"], "type": "Credit Card", "status": "Active",
            "balance_account": card["Account"], "account_id": card["Account ID"]})
        res["credit_entry"] = True
    return res


_accounts = CardCollection(
    slug="accounts",
    store=accounts,
    id_field="Account ID",
    title_field="Account",
    group_by="Type",
    heading="Accounts",
    noun="accounts",
    item_noun="account",
    can_create=True,
    can_delete=True,
    on_create=_on_create,
    fan_out=_fan_out,
    before_update=_before_update,
    page_overlay=_page_overlay,
    banner=_feed_banner,
    banner_template="accounts_feed_strip.html",
    fields=[
        CardField("Account Kind", "select", options=list(ACCOUNT_TYPES)),
        CardField("Account"), CardField("Ticker"), CardField("Institution"),
        CardField("Brokerage"),
        CardField("Type"), CardField("Group"), CardField("Category"),
        CardField("Account Type"),
        CardField("Amount", "number"), CardField("Shares", "number"),
        CardField("Purchase Price", "number"), CardField("Opening Balance", "number"),
        CardField("Balance Owed", "number"), CardField("Status"),
        CardField("APR %", "number"), CardField("Annual Fee", "number"),
        CardField("Credit Limit", "number"), CardField("Min Payment", "number"),
        CardField("Opened Date"), CardField("Age (Last Date)"),
        CardField("Usage Notes", "textarea"),
    ],
    amount=lambda d: d.get("Amount"),
    subtitle=lambda d: d.get("Category") or None,
    numeric_mode="coerce_float",
    section_order=["Assets", "Equity", "Liabilities"],
    unclassified_label="(unclassified)",
    filter=_accounts_filter,
    statuses=["active", "closed", "all"],
    extra_actions=[{"id": "card-add-balance", "label": "➕ Add to Balances"}],
    client_config={
        "typeField": "Account Kind",
        "types": {k: v["fields"] for k, v in ACCOUNT_TYPES.items()},
        "linked": {k: v.get("linked") for k, v in ACCOUNT_TYPES.items() if v.get("linked")},
        "editFields": EDIT_FIELDS,
        "linkedEditable": sorted(LINKED_EDITABLE),
    },
)

# --- archive / reopen (linked accounts: delete is replaced by this paired action) -----
# Registered BEFORE the CardCollection routes so /api/accounts/<doc_id> can't shadow them.

def _set_lifecycle(request, *, closed: bool):
    """Archive or reopen a card together with its detail record. Nothing is deleted;
    balance history is untouched, so past balance sheets keep their truth."""
    body = web.read_json(request)
    doc = accounts.get(body.get("id"))
    if not doc:
        return _err("account not found", 404)
    accounts.update(doc["_id"], {"Status": "Closed" if closed else "Active"})
    kind = linked_kind(doc)
    if kind == "portfolio":
        # the portfolio status flag: refresh, sync, and the page all honor it
        portfolio.update_where({"account_id": doc["Account ID"]}, {"_closed": closed})
    elif kind == "credit":
        for e in credit_accounts.list({"account_id": doc["Account ID"]}):
            credit_accounts.update(e["_id"], {"status": "Closed" if closed else "Active"})
    return web.json({"ok": True, "status": "Closed" if closed else "Active"})


@web.POST
def _archive(request):
    return _set_lifecycle(request, closed=True)


@web.POST
def _reopen(request):
    return _set_lifecycle(request, closed=False)


# --- unlinked feed accounts: Link / Promote / Ignore (app/simplefin/link.py) ----------------

@web.GET
def _feed_unlinked(request):
    return web.json(_feed_banner(None) or {"unlinked": [], "ignored": [], "cards": [], "kinds": PROMOTABLE})


@web.POST
def _feed_link_route(request):
    body = web.read_json(request)
    return web.json(feed_link.link(body.get("feed_id"), body.get("card_id")))


@web.POST
def _feed_promote_route(request):
    return web.json(_promote(web.read_json(request)))


@web.POST
def _feed_ignore_route(request):
    return web.json(feed_link.ignore(web.read_json(request).get("feed_id")))


@web.POST
def _feed_unignore_route(request):
    return web.json(feed_link.unignore(web.read_json(request).get("feed_id")))


urlpatterns = [
    path("api/accounts/archive", _archive),
    path("api/accounts/reopen", _reopen),
    path("api/accounts/unlinked", _feed_unlinked),
    path("api/accounts/link", _feed_link_route),
    path("api/accounts/promote", _feed_promote_route),
    path("api/accounts/ignore", _feed_ignore_route),
    path("api/accounts/unignore", _feed_unignore_route),
    *_accounts.urlpatterns(),
]
