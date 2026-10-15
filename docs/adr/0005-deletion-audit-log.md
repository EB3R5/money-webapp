# Hard-delete, but snapshot to a `deletions` audit log first

Deleting a row removes it from its collection (a hard delete), but every delete first copies the
full pre-delete documents into a single `deletions` collection (`{collection, doc, deleted_at}`).
This is done by `app/audit.py::log_deletions`, called from the grid/card delete machinery
(ledger, balances, inventory), the registry delete machinery (`app/registry.py` — credit
accounts/scores/activity, tax history, savings goals, health periods), and the budget-version
delete.

We chose this over an in-place soft-delete flag (e.g. `_deleted: true`) because the grids and
card queries stay simple — they never have to filter out tombstones — while nothing is truly
unrecoverable. The audit log is also a uniform place to look across collections.

_Consequence:_ recovery is manual (re-insert from `deletions`); there is no UI to undo a delete.
The confirm dialogs say so explicitly.

_Addendum 2026-09-21 (SQLite-first), amended 2026-10-04 (ADR-0020):_ an Item's, a Software row's or a Kit's photo Blobs and file-Document Blobs stay in `blobs` after the row is deleted, so a row restored from `deletions` gets its bytes back; `scripts/prune_blobs.py` removes Blobs no live row or deletion snapshot references, dry-run by default. (Before 2026-10-04 the same rule applied to files under `photos/`; the `prune_photos.py` it named was never written.)
