# The feed yields to hand edits, per field

Decided 2026-10-03 (plan: `docs/plans/2026-10-03-002-fix-ledger-edits-survive-sync-plan.md`).
Amends ADR-0014's "the feed owns the provider facts": it owns them **until a person edits one**.

A Ledger edit on a feed Transaction (Date, Description, Amount, Account, Institution) used to
hold only until the next Sync run, which re-reads a ~5-day window and treated any difference
between the row and the bank as a bank change. Category survived because it is app-owned; the
provider fields did not. The fix is the Software board's "automatic Status" rule generalised:
each feed Transaction keeps the feed's **last-applied value per provider field** (`_provider`,
a JSON snapshot refreshed every run). On a run, per field: the bank's value differs from the
snapshot and the row's does not → the bank changed it, write it; the row's value differs from
the snapshot → a person changed it, keep it — **whatever the bank says now**. A hand edit wins
for good on that field; the other fields keep receiving bank corrections. `Month` is derived
from the effective Date, not snapshotted.

Why hand-wins-always rather than "until the bank changes that field": the one common bank
change is a pending Transaction posting with a new date and description, and a date corrected
for a report must not snap back when that happens. A person who wants the bank's value back
can re-type it. Pending reconciliation follows the same rule: a pending row is matched to its
posted twin on the **bank's** Amount and description, and the person's edits ride onto the
posted row, where they are hand edits from then on.

A row synced before migration 0013 has no snapshot: its first run keeps every current value
and starts the snapshot from the bank's values — no backfill, which would have turned an edit
made just before the deploy into a "bank value". A deleted-and-reinserted feed row (an account
ignored, then re-linked) loses its edits, as before.
