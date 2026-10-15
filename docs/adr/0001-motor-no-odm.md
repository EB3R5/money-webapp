# Query Mongo directly with Motor, no ODM, keep spreadsheet field names

_Status: superseded by ADR-0010 and ADR-0011 (2026-09-21): the database is SQLite and each store module owns its SQL. The spreadsheet-style field names survive as each store's field map (ADR-0012)._

The migrated collections use spreadsheet-style field names (`"Account Type"`, `"Unit_Cost"`,
`"APR %"`) rather than Python-friendly identifiers. We query them directly with Motor (async)
instead of mapping them through an ODM like Beanie, because the source of truth is the sheet
and forcing those names into models would add a translation layer for little gain at this
scale. A future app-authored, clean collection can adopt an ODM without disturbing the
spreadsheet-backed ones.

_Consequence:_ field names appear as string literals across routers (`COLUMNS`, `FIELD` maps),
and there is no schema enforcement — values are validated at the edit endpoint, not by the DB.
