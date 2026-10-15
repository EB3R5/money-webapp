# SimpleFIN is the only live feed; the Sheets path is gone

Decided 2026-09-24 (plan: `docs/plans/2026-09-24-001-feat-simplefin-only-feed-plan.md`).
Status: done; the cut-over ran 2026-09-25 and the one-off seam reconciler, calibration report
and Atlas export were removed afterwards.
Supersedes the sync half of ADR-0013 and the "the Sheets sync keeps working unchanged"
consequence of ADR-0014.

The Tiller → Google Sheets → app pipeline is removed: the nightly Sheets sync, its router
and Sync buttons, the import kit (`migration/`), the Tiller predecessor (`tiller_sync/`), the
service-account and spreadsheet settings, and the `sync_state` table. Transactions, accounts,
and balances arrive from the SimpleFIN Bridge (ADR-0014) and from what a person types; nothing
else writes them. The Mongo handle and its test double leave with the last reader, so the app
starts with a data directory and a session secret and nothing else (ADR-0010).

Tiller history stays. Every row the Sheets era wrote keeps its id and its fields; a Tiller
row is history, not a source, and the seam between it and the feed is reconciled once at
cut-over (a separate slice). The one-time Atlas export remains a private script behind the
`export` extra, the only place `pymongo` is still a dependency.

_Consequence:_ a fresh install has no import path for spreadsheet data; a person with Tiller
history brings it through the export, or not at all. The Activity page shows one feed. The
production compose service mounts no service-account key.
