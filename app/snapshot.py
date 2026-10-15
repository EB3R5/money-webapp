"""Snapshot writer — the one module that builds and persists balance-history Snapshots.

A Snapshot is one dated `balance_history` row recording an Account's Balance (CONTEXT.md).
Three writers port external values into balance history as Snapshots — the investments
portfolio (app/investments.py), the inventory rollup (app/inventory_sync.py), and the
Add-account fan-out (app/views/accounts.py). Each is a thin adapter that maps its rows to
the field values and calls `snapshot_doc` + `append`; this module owns the shape once.

Snapshots are records: every sync appends dated rows and never rewrites earlier ones, so the
balance sheet's Starting/Ending/Max per month reads real within-month movement.

`account_id` is deliberately byte-stable: the same input always yields the same Account ID,
so every record of an account carries the same identifier. Feed rows carry no Account #
(the Tiller-era masked number); nothing keys on it any more."""

import hashlib
import re
from datetime import UTC, datetime

from .store.balance_history import balance_history


def slug(s) -> str:
    """'Cash & Equivalents' -> 'cash_equivalents' — for stable `_id` suffixes."""
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def account_id(*parts) -> str:
    """Stable 24-char hex id from sha256 of the |-joined, trimmed, lowercased parts.

    Parts are joined in the given order, so callers control the key shape:
    portfolio uses (institution, source_account, asset); inventory uses
    (institution, 'inventory', category)."""
    key = "|".join("" if p is None else str(p).strip().lower() for p in parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def snapshot_doc(*, _id, account, balance, category, group, type_, account_type, cls,
                 institution, acct_id, src, when=None) -> dict:
    """Assemble one Snapshot (API-shaped, for the balance_history store). `type_` is the
    coarse category-derived kind (Assets / Liabilities / Equity); `account_type` is the
    Balances grid's granular 'Account Type'; `cls` is the balance-sheet grouping."""
    when = when or datetime.now(UTC)   # real timestamp: intra-day records must order
    return {
        "_id": _id,
        "Date": when,
        "Account": account,
        "Account ID": acct_id,
        "Category": category,
        "Group": group,
        "Type": type_,
        "Account Type": account_type,
        "Class": cls,
        "Institution": institution,
        "Balance": round(balance, 2),
        "_src": src,
    }


def append(src: str, docs: list) -> dict:
    """Record the current snapshot set as new dated rows. Nothing is deleted — prior
    records stay as history. Returns the summary every sync source reports:
    {ok, lines, total, accounts}."""
    if docs:
        balance_history.insert_many(docs)
    return {
        "ok": True,
        "lines": len(docs),
        "total": round(sum(d["Balance"] for d in docs), 2),
        "accounts": [d["Account"] for d in docs],
    }
