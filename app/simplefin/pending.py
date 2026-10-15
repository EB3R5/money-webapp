"""Pending reconciliation — a pending Transaction that reappears posted under a different
provider id must not become two rows.

First pass, after a run's inserts: for each posted Transaction inserted this run, look
for pending rows in the same provider account with a different id, the same Amount, a
Date within ±3 days, and a description that is equal or a prefix of the other once
normalized — Amount and description are the *bank's* values (`provider_value`, ADR-0019),
so a pending row the person edited still finds its twin. Exactly one candidate: carry the
app-owned fields (Category and its derived fields, categorized date, ML suggestion) and the
person's hand edits onto the posted row, audit the pending row to deletions with reason
`pending_replaced`, delete it. Zero or several: leave everything — a wrong merge is worse
than a duplicate the user can see.

Second pass: pending rows that no run has seen for 7 days are gone from the provider;
they are audited as `pending_vanished` and deleted. The rows judged are those dated
inside the chunk's window widened back by the vanish period: with a 5-day overlap a
pending row leaves every later window before it has been unseen for 7 days, so the
window alone would never catch one — the widening judges it once, after the runs during
the overlap had their chance to see it again. A row whose same id flips pending → posted
is already handled by the plain upsert."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from ..store.deletions import deletions
from ..store.transactions import HAND_EDITABLE, hand_edits, provider_same, provider_value, transactions

MATCH_DAYS = 3
VANISH_DAYS = 7
# App-owned fields carried from the pending row onto its posted twin.
CARRY = ("Category", "Group", "Type", "Cashflow Type", "Budget", "Timing",
         "Categorized Date", "Pred:Category", "Pred:Conf")

_WS = re.compile(r"\s+")


def normalize(desc) -> str:
    return _WS.sub(" ", str(desc or "").strip().lower())


def descriptions_match(a, b) -> bool:
    """Equal after normalization, or one is a prefix of the other (banks often append
    the posting reference or trim the pending text)."""
    x, y = normalize(a), normalize(b)
    if not x or not y:
        return x == y
    return x == y or x.startswith(y) or y.startswith(x)


def replace_pending(posted: dict) -> bool:
    """Merge the single pending twin of a newly posted row into it. True when one was."""
    candidates = [c for c in transactions.pending_twins(
        posted["provider_account_id"], posted_day=posted["Date"],
        exclude_txn_id=posted["provider_txn_id"], days=MATCH_DAYS)
        if provider_same("Amount", provider_value(c, "Amount"), provider_value(posted, "Amount"))
        and descriptions_match(provider_value(c, "Description"), provider_value(posted, "Description"))]
    if len(candidates) != 1:
        return False
    twin = candidates[0]
    carried = {k: twin[k] for k in CARRY if twin.get(k) not in (None, "")}
    # The person's edits on the pending row ride along; the posted row's snapshot holds the
    # bank's values, so they count as hand edits there too and later runs keep them.
    carried.update({k: v for k, v in hand_edits(twin).items() if k in HAND_EDITABLE})
    if carried:
        transactions.update(posted["_id"], carried)
    deletions.log("transactions", [twin], reason="pending_replaced")
    transactions.delete(twin["_id"])
    return True


def reconcile_inserted(inserted_posted: list[dict]) -> int:
    """First pass over this run's newly inserted posted rows; returns replacements made."""
    n = 0
    for row in inserted_posted:
        if replace_pending(row):
            n += 1
    return n


def drop_vanished(provider_account_id: str, *, window_start: datetime, window_end: datetime,
                        now: datetime, days: int = VANISH_DAYS) -> int:
    """Second pass: audit and delete pending rows dated in [window_start − days, window_end)
    that no run has seen for `days`."""
    stale = transactions.stale_pending(
        provider_account_id, window_start=window_start - timedelta(days=days), window_end=window_end,
        unseen_since=now - timedelta(days=days))
    if stale:
        deletions.log("transactions", stale, reason="pending_vanished")
        for row in stale:
            transactions.delete(row["_id"])
    return len(stale)
