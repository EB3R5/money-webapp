# One Sheets import path, no raw stage; sync and ML are optional layers

_Superseded in part by ADR-0015 (2026-09-24): the Sheets import and its nightly sync are removed; the ML layer's optionality stands._

Supersedes the scratch-database rule of ADR-0009. The import kit (`migration/`) no longer
mirrors spreadsheet tabs into raw collections and then promotes them. It is `discover`
(manifest of tabs), `import` (a Sheets tab straight into an app table through that entity's
store, one mapper per source tab), and `verify`. The nightly `sheets_sync` is the same import
path run incrementally, protecting the app-owned fields on rows that already exist. The
mappers live in `app/sheets_io.py`, one per source tab, used by both; the transaction
synthetic id keeps the transform's recipe (date, description, amount, account). The raw
tier's reasons (re-runnable migration, reconciliation, recovery) are met by the export's
census check and the archived Atlas dump.

Sheets sync and the ML categorizer are optional layers. The scheduler registers the sync job
only when `SHEET_ID` and `GOOGLE_SA_JSON` are set, and the Sync control reports "not
configured" otherwise; predict and retrain already degrade to no-ops without a model. The
placeholder 03:00 rollup job is removed. A stranger runs the app with neither Google nor a
model; an install that has them keeps both.

_Consequence:_ there is exactly one mapping from a Tiller row to a transaction, and the two
copies that had drifted apart (sync vs transform) are gone.
