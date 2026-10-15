# Retire the raw tier from the live database; raw mirrors live in a scratch database or the dump

_Status: moot since ADR-0010 and ADR-0015 (2026-09-24): the database is SQLite and the Sheets import path is gone; kept as the record of why `inventory` and `portfolio` are app-owned tables._

Supersedes ADR-0002. The live app database holds only the collections the app itself owns and
writes (about two dozen: the clean tier, the registries, mappings, budgets, users, the deletion
log, GridFS buckets, and the two derived docs `appHealth` and `sync_state`). The ~65
`raw__<sheet>__<tab>` mirrors are dropped after a verified offline dump; nothing in the app read
them by name, and the reconciliation and recovery role ADR-0002 gave them is served by the dump
instead. Two mirrors the app had been writing directly (inventory, current portfolio) are kept
and promoted to clean names, because they are app state, not mirrors.

Future imports never write `raw__` collections into the live database. `migration/raw_load.py`
targets a scratch database (a different `MONGO_DB`), and promotion into the app database is an
explicit, separate step. This closes the hazard where a re-run of the loader would `delete_many`
a collection the app owns.

_Consequence:_ the generic Sheets grid no longer has a raw tier to browse, and its future is
decided separately. Anything wanted from an old workbook tab is restored from the dump into a
scratch database, never into the app database.
