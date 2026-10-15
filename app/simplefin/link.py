"""Feed accounts: unlinked on arrival; Link, Promote, Ignore (D3, D8, D9, D10).

A bank account the Bridge reports for the first time becomes a hidden placeholder row in
`accounts` (`Status` Unlinked, `is_hidden`), never a card. Its transactions and Snapshots
still collect under the placeholder's name so nothing is missed while a person decides.
The decision is one of three operations, each audited:

  link     attach the feed account to an existing card: the feed columns move onto the
           card, the feed's transactions take the card's Account and Institution, its
           Snapshots re-key to the card's Account ID and classification, and the
           placeholder is deleted (`deletions`, reason feed_linked). From then on the
           sync finds the card by `simplefin_account_id` and writes under it.
  promote  make the placeholder a card of its own: a minted Account ID, the chosen
           type's classification preset, Status Active, visible; its Snapshots re-key.
  ignore   keep the row hidden (Status Ignored) so it is not re-offered, remove the rows
           it already collected (reason feed_ignored), and have the sync skip its
           transactions and Snapshots from now on. `unignore` reverts to Unlinked.

No Account # is ever written for feed rows (D10)."""

from __future__ import annotations

import secrets

from ..store.accounts import accounts
from ..store.balance_history import balance_history
from ..store.deletions import deletions
from ..store.transactions import transactions
from ..web import DomainError

FEED = "simplefin"
UNLINKED = "Unlinked"
IGNORED = "Ignored"
FEED_COLUMNS = ("simplefin_account_id", "connection_id", "currency", "available",
                "balance_date", "last_seen_at")


def placeholder_row(a_id: str, name: str, provider: dict) -> dict:
    """The row the sync inserts for a bank account it has not seen before."""
    return {"_id": "sfa_" + secrets.token_hex(10), **provider,
            "Account": name or a_id, "Account ID": a_id, "Status": UNLINKED, "is_hidden": True}


def is_placeholder(row: dict | None) -> bool:
    return bool(row) and bool(row.get("is_hidden")) and (row.get("Status") in (UNLINKED, IGNORED))


def is_ignored(row: dict | None) -> bool:
    return bool(row) and row.get("Status") == IGNORED


def unlinked() -> list[dict]:
    """Placeholders awaiting a decision, by name."""
    return accounts.list({"Status": UNLINKED, "is_hidden": True}, order=[("Account", "asc")])


def ignored() -> list[dict]:
    return accounts.list({"Status": IGNORED, "is_hidden": True}, order=[("Account", "asc")])


def _placeholder(feed_id: str) -> dict:
    row = accounts.get(feed_id)
    if not is_placeholder(row):
        raise DomainError("not an unlinked feed account", status=404)
    return row


def _classification(card: dict) -> dict:
    return {"Class": card.get("Type"), "Type": card.get("Type"), "Group": card.get("Group"),
            "Category": card.get("Category"), "Account Type": card.get("Account Type")}


def _rekey_rows(placeholder: dict, card: dict) -> tuple[int, int]:
    """Move the placeholder's transactions and Snapshots under `card`."""
    pid = placeholder["simplefin_account_id"]
    institution = card.get("Institution") or placeholder.get("Institution")   # the card's, else the bank's name
    txns = transactions.update_where(
        {"provider_account_id": pid},
        {"Account": card.get("Account"), "Institution": institution})
    snaps = balance_history.update_where(
        {"Account ID": placeholder.get("Account ID"), "_src": FEED},
        {"Account ID": card.get("Account ID"), "Account": card.get("Account"),
         "Institution": institution, **_classification(card)})
    return txns, snaps


def link(feed_id: str, card_id: str) -> dict:
    """Attach a placeholder to an existing card. Returns {ok, card, transactions, snapshots}."""
    placeholder = _placeholder(feed_id)
    card = accounts.get(card_id)
    if not card or card.get("is_hidden"):
        raise DomainError("card not found", status=404)
    if card.get("simplefin_account_id"):
        raise DomainError("that card is already linked to a feed account", status=409)
    if not card.get("Account ID"):
        raise DomainError("that card has no Account ID to link under", status=409)
    accounts.update(feed_id, {"simplefin_account_id": None})   # the unique index moves with it
    accounts.update(card_id, {k: placeholder.get(k) for k in FEED_COLUMNS})
    card = accounts.get(card_id)
    txns, snaps = _rekey_rows(placeholder, card)
    deletions.log(accounts.table, [placeholder], reason="feed_linked")
    accounts.delete(feed_id)
    return {"ok": True, "card": card_id, "transactions": txns, "snapshots": snaps}


def promote(feed_id: str, kind: str, preset: dict) -> dict:
    """Make a placeholder a card of its own with `preset`'s classification (Type, Group,
    Category, Account Type) for `kind`. Returns {ok, card, account_id, snapshots}."""
    placeholder = _placeholder(feed_id)
    if not preset:
        raise DomainError("choose an account type")
    account_id = "MAN-" + secrets.token_hex(4).upper()
    accounts.update(feed_id, {**preset, "Account Kind": kind, "Account ID": account_id,
                                    "Status": "Active", "is_hidden": False})
    card = accounts.get(feed_id)
    snaps = balance_history.update_where(
        {"Account ID": placeholder.get("Account ID"), "_src": FEED},
        {"Account ID": account_id, **_classification(card)})
    return {"ok": True, "card": feed_id, "account_id": account_id, "snapshots": snaps}


def ignore(feed_id: str) -> dict:
    """Hide a feed account for good: the rows it collected are audited away and the sync
    skips it from now on. Returns {ok, transactions, snapshots}."""
    placeholder = _placeholder(feed_id)
    pid = placeholder["simplefin_account_id"]
    txns = transactions.list({"provider_account_id": pid})
    deletions.log(transactions.table, txns, reason="feed_ignored")
    n_txns = transactions.delete_where(provider_account_id=pid) if txns else 0
    snaps = balance_history.list({"Account ID": placeholder.get("Account ID"), "_src": FEED})
    deletions.log(balance_history.table, snaps, reason="feed_ignored")
    n_snaps = (balance_history.delete_where(_id=[s["_id"] for s in snaps])) if snaps else 0
    accounts.update(feed_id, {"Status": IGNORED})
    return {"ok": True, "transactions": n_txns, "snapshots": n_snaps}


def unignore(feed_id: str) -> dict:
    row = accounts.get(feed_id)
    if not is_ignored(row):
        raise DomainError("not an ignored feed account", status=404)
    accounts.update(feed_id, {"Status": UNLINKED})
    return {"ok": True}
