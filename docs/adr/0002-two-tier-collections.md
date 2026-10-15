# Two-tier collections: raw verbatim mirror + clean domain collections

_Status: superseded by ADR-0008 (2026-09-21) — the raw tier no longer lives in the app database._

The migration loads every spreadsheet tab verbatim into a `raw__<sheet>__<tab>` collection
(replaced wholesale each run — an idempotent, exact mirror), then promotes only the *source*
tabs into clean domain collections (`transactions`, `accounts`, `balanceHistory`, `categories`,
`autocat`). Computed and report tabs are deliberately left raw-only, because the app recomputes
those (P&L, Balance Sheet) from the clean collections rather than trusting a stale spreadsheet
calculation.

We keep the raw tier even after promoting, so the migration is re-runnable, reconciliation is
possible to the cent, and pages like Sheets can browse any tab without a bespoke importer.

_Consequence:_ data is duplicated between tiers; the raw tier is the recovery/audit source
(e.g. restoring a clobbered field from `raw__inventory_foundation__inventorysnapshot`).
