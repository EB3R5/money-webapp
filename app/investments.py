"""Investments — the current portfolio, with live price refresh and a sync into
balance history.

Source is the `portfolio` store: one row per holding with Asset (ticker), Shares,
Avg/Purchase price, Current Price, Current Value, etc. — REAL columns (ADR-0012; the
earlier spreadsheet tooling stored money strings). Live quotes come from yfinance (free,
no API key). refresh_prices() fetches the current price per ticker and rewrites Current
Price / Current Value / Return / Delta in place. sync_portfolio_to_balances() ports each
holding into balance history as Equity (cash → Assets), idempotently, so the portfolio
shows up on the balance sheet.
"""

from datetime import UTC, date, datetime

from . import snapshot
from .store.accounts import accounts
from .store.balance_history import balance_history
from .store.portfolio import portfolio
from .card_collection import num0, to_float

SYNC_SRC = "portfolio_sync"
DEFAULT_INSTITUTION = "Investments"
ACCOUNT_PREFIX = "INV"


def money(v):
    """-3605.29 -> '-$3,605.29' to match the source string format."""
    return ("-$" if v < 0 else "$") + f"{abs(v):,.2f}"


def shares_str(n):
    """12.0 -> '12', 12.5 -> '12.5' — the source's plain number string for Shares."""
    return f"{n:.6f}".rstrip("0").rstrip(".") or "0"


def position_values(shares, price, cost):
    """Current Value / Return / Delta for a position — the math refresh_prices and holding
    edits share. Numbers, Delta a fraction (the store's REAL columns)."""
    value = shares * price
    ret = value - cost
    delta = (ret / cost) if cost else 0.0
    return {"Current Value": round(value, 2), "Return": round(ret, 2), "Delta": round(delta, 6)}


def open_holdings() -> list[dict]:
    """Every holding not archived (`_closed`)."""
    return [h for h in portfolio.list() if not h.get("_closed")]


def is_cash(asset):
    a = (asset or "").strip().lower()
    return "cash" in a


def normalize_ticker(asset):
    """Yahoo symbol for a holding: 'BRK.B' -> 'BRK-B'. None for cash / blank."""
    a = (asset or "").strip()
    if not a or is_cash(a):
        return None
    return a.upper().replace(".", "-")


# --- live price fetch (yfinance == the GOOGLEFINANCE equivalent) -------------

def fetch_prices(symbols):
    """{yahoo_symbol: last_price} via yfinance. Defensive per-ticker — a failed or
    unknown symbol is simply omitted, never raised."""
    import yfinance as yf

    out = {}
    for s in symbols:
        try:
            price = yf.Ticker(s).fast_info.last_price
            if price:
                out[s] = float(price)
        except Exception:
            continue
    return out


def refresh_prices(price_fn=None):
    """Refresh Current Price / Value / Return / Delta for every real-ticker holding.
    `price_fn` is injectable for tests; defaults to the live yfinance fetch."""
    price_fn = price_fn or fetch_prices
    holdings = open_holdings()
    targets = [(h, normalize_ticker(h.get("Asset"))) for h in holdings]
    targets = [(h, sym) for h, sym in targets if sym and num0(h.get("Shares"))]

    prices = price_fn(sorted({sym for _h, sym in targets}))

    updated, failed, accounts_synced = 0, [], 0
    for h, sym in targets:
        p = prices.get(sym)
        if not p:
            failed.append(h.get("Asset"))
            continue
        shares = num0(h.get("Shares"))
        value = shares * p
        portfolio.update(h["_id"], {
            **position_values(shares, p, num0(h.get("Purchase Price"))),
            "Current Price": round(p, 4),
            "_price_updated_at": datetime.now(UTC),
        })
        updated += 1
        # Propagate the refreshed value into the matching Accounts card (Account ==
        # the holding's ticker), so the Accounts page reflects live totals instead of
        # a stale migrated Amount. No-op when no such account row exists (e.g. cash).
        accounts_synced += accounts.update_where(
            {"Account": h.get("Asset")}, {"Amount": round(value, 2)})
    return {"ok": True, "updated": updated, "failed": failed,
            "accounts_synced": accounts_synced}


# --- position-fact edits ------------------------------------------------------

def update_holding(holding_id, body):
    """Edit a holding's position facts — Shares, Purchase Price, Brokerage (stored
    as the holding's `Account`) — and recompute its value fields at the last known
    price. Anything outside that whitelist is ignored, never written. Returns
    (payload, status) in the card pages' ok/error envelope."""
    update = {}
    for field in ("Shares", "Purchase Price"):
        if field in body:
            n = to_float(body[field])
            if n is None or n <= 0:
                return {"ok": False, "error": f"{field} must be a positive number"}, 400
            update[field] = n
    if "Brokerage" in body:
        update["Account"] = str(body["Brokerage"] or "").strip()
    if not update:
        return {"ok": False, "error": "no editable fields"}, 400

    holding = portfolio.get(holding_id)
    if not holding:
        return {"ok": False, "error": "unknown holding"}, 404
    if holding.get("_closed"):
        return {"ok": False, "error": "holding is archived"}, 400

    sets = {k: v for k, v in update.items() if k == "Account"}
    if "Shares" in update or "Purchase Price" in update:
        # Price the position at the last known price — never at a price derived
        # from the post-edit shares, which would neutralize the edit.
        pre_shares = num0(holding.get("Shares"))
        price = num0(holding.get("Current Price"))
        if not price and pre_shares:
            price = (num0(holding.get("Purchase Price")) / pre_shares
                     or num0(holding.get("Current Value")) / pre_shares)
        if not price:
            return {"ok": False, "error": "no price basis to value this holding"}, 400
        shares = update.get("Shares", pre_shares)
        cost = update.get("Purchase Price", num0(holding.get("Purchase Price")))
        if "Shares" in update:
            sets["Shares"] = shares
        if "Purchase Price" in update:
            sets["Purchase Price"] = round(cost, 2)
        sets.update(position_values(shares, price, cost))
        sets["Avg Cost"] = round(cost / shares, 4)
    portfolio.update(holding_id, sets)
    return {"ok": True}, 200


# --- page rows ---------------------------------------------------------------

def portfolio_rows(holdings):
    """Parsed holdings for the Investments page (skips the trailing totals row)."""
    rows = []
    for h in holdings:
        asset = (h.get("Asset") or "").strip()
        if not asset:
            continue
        shares = num0(h.get("Shares"))
        value = num0(h.get("Current Value"))
        cost = num0(h.get("Purchase Price"))
        ret = value - cost if (value or cost) else num0(h.get("Return"))
        rows.append({
            "_id": str(h["_id"]) if h.get("_id") is not None else None,
            "asset": asset,
            "account": h.get("Account") or "",
            # Modal prefill, keyed by the editor's field names — the read-side
            # mirror of update_holding's write mapping (Brokerage ↔ Account).
            "Shares": h.get("Shares") or "",
            "Purchase Price": h.get("Purchase Price") or "",
            "Brokerage": h.get("Account") or "",
            "shares": shares,
            "avg_cost": num0(h.get("Avg Cost")),
            "price": num0(h.get("Current Price")),
            "value": round(value, 2),
            "cost": round(cost, 2),
            "ret": round(ret, 2),
            "delta": (ret / cost) if cost else 0.0,
            "is_cash": is_cash(asset),
            "updated_at": h.get("_price_updated_at"),
        })
    rows.sort(key=lambda r: r["value"], reverse=True)
    total_value = round(sum(r["value"] for r in rows), 2)
    total_cost = round(sum(r["cost"] for r in rows), 2)
    total = {
        "value": total_value, "cost": total_cost,
        "ret": round(total_value - total_cost, 2),
        "delta": ((total_value - total_cost) / total_cost) if total_cost else 0.0,
    }
    return rows, total


# --- portfolio -> balance-sheet mapping ---------------------------------------

def map_category(c):
    return {"Common Stock": "Common Stock", "Cash Equivalent": "Cash & Equivalents",
            "Individual Stock": "Common Stock", "Liquid": "Cash & Equivalents",
            "Cash": "Cash & Equivalents"}.get(c, c or "Common Stock")


def map_group(g):
    return {"Equity": "Stockholder's Equity", "Cash": "Current Assets",
            "Individual Stock": "Stockholder's Equity",
            "Liquid": "Current Assets"}.get(g, "Stockholder's Equity")


def map_type(t):
    return {"Equity": "Equity", "Individual Stock": "Equity", "Cash": "Assets",
            "Liquid": "Assets", "Cash Equivalent": "Assets"}.get(t, "Equity")


def build_balance_doc(holding, when=None):
    """Map one holding to a balanceHistory Snapshot (shape owned by app/snapshot.py)."""
    asset = (holding.get("Asset") or "").strip()
    cash = is_cash(asset)
    cat = map_category("Cash Equivalent" if cash else holding.get("Category"))
    grp = "Current Assets" if cash else map_group(holding.get("Group"))
    typ = "Assets" if cash else map_type(holding.get("Type"))
    institution = holding.get("Account") or DEFAULT_INSTITUTION
    when = when or datetime.now(UTC)
    return snapshot.snapshot_doc(
        _id=f"portsync_{snapshot.slug(asset)}_{int(when.timestamp() * 1_000_000)}",
        account=asset,
        balance=num0(holding.get("Current Value")),
        category=cat,
        group=grp,
        type_=typ,                  # Equity (stocks) / Assets (cash) → balance sheet
        account_type=cat,           # Balances grid "Account Type"
        cls=typ,                    # balance-sheet grouping (Equity holds brokerage)
        institution=institution,
        # A holding created by the Add-account fan-out carries its card's Account ID —
        # one ID across the account's whole snapshot stream. Legacy holdings keep the
        # synthesized hash (no backfill).
        acct_id=holding.get("account_id")
                or snapshot.account_id(institution, holding.get("Account"), asset),
        src=SYNC_SRC,
        when=when,
    )


def sync_portfolio_to_balances():
    """Record the current portfolio in balanceHistory as new dated rows — every sync
    appends, so re-syncing through the month builds the within-month history the balance
    sheet's Starting/Ending columns read.

    A holding whose Account already has a non-portfolio row this month (a manual stamp,
    a Tiller-era balance) is skipped — that balance stays authoritative for the month.
    Creation snapshots (_src "account_create") don't count: a stock added mid-month keeps
    syncing for the rest of that month."""
    when = datetime.now(UTC)
    holdings = open_holdings()
    docs = [build_balance_doc(h, when) for h in holdings
            if (h.get("Asset") or "").strip() and num0(h.get("Current Value"))]

    month_start = datetime(when.year, when.month, 1)
    taken = balance_history.accounts_with_rows_since(
        month_start, exclude_src=[SYNC_SRC, "account_create"])
    skipped = sorted(d["Account"] for d in docs if d["Account"] in taken)

    summary = snapshot.append(
        SYNC_SRC, [d for d in docs if d["Account"] not in taken])
    summary["skipped"] = skipped
    return summary
