# Denormalize category-derived fields onto each transaction

_Amended 2026-09-24: `categories` is a table and the rollups are SQL `GROUP BY` queries (ADR-0011); the decision stands as written._

A Transaction stores not just its `Category` but the fields derived from that category —
`Group`, `Budget`, `Cashflow Type`, `Timing`, `Type` — copied from the `categories` collection
at write time. When a Transaction's Category changes (via `/api/transactions/category`), the
derived fields are re-looked-up and rewritten; they are never editable directly.

We denormalize rather than join-on-read because reports and the dashboard group by `Group`/`Type`
over the whole ledger, and carrying those on the row keeps the Mongo aggregation pipelines simple
and fast. The `categories` collection stays the single source of the mapping.

_Consequence:_ if a category's mapping changes, existing transactions keep their old derived
values until re-saved. A future rollup/backfill job would need to refresh them.
