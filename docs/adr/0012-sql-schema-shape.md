# SQL schema: snake_case typed columns, JSON for nested values, string ids kept

Tables use snake_case column names (`account_number`, `cashflow_type`, `unit_cost`,
`pred_category`); each store module carries a field map so the API JSON and the JS islands keep
the spreadsheet-style keys they already use. Columns are typed: REAL for money and quantities,
INTEGER for counts, TEXT ISO-8601 for dates and timestamps. The one-time export parses the
source-typed strings once (inventory `Qty`, portfolio `Shares` and dollar strings) and the store
serializer formats for display, so "source-typed value" leaves the vocabulary and ADR-0007
keeps only its dirty-diff rule. ADR-0001's "keep spreadsheet field names in the database" is
retired; the names survive at the API edge only.

Nested values (`Pred:Conf`, deletion snapshots, sync state, health snapshot, model filters,
inventory image lists) are TEXT columns holding JSON, read with JSON1. Budget lines get a child
table so the pivot can query by category. Migration leftovers (`_src`, `_transformed_at`,
`_synced_at`, stray `colN`, `Type__15`, `Updated__20`) are dropped at export; every table has
`created_at` and `edited_at`.

Ids: existing string ids are kept as `id TEXT PRIMARY KEY`; rows that had ObjectIds (users,
deletions) get uuids at export; new rows get uuid4. Indexes follow what the grids sort and
search by (transactions date and category, balance history account and date, a unique on the
transaction id). Grid search is `LIKE ... COLLATE NOCASE` over the searched columns; FTS5 is
deferred until the ledger's row count makes it necessary.

The schema document is generated, not drawn: `scripts/schema_doc.py` reads `sqlite_master` and
`PRAGMA table_info` and writes `docs/schema.mmd`; the rendered HTML is gone.

_Consequence:_ every store's field map is the single place a column name meets a JSON key; a
new field is added in the schema file, the map, and nowhere else.
