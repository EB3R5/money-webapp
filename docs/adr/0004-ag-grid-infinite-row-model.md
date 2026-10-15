# AG Grid Community Infinite Row Model with a per-collection block datasource

_Amended 2026-09-24: the block datasource is a SQL `LIMIT/OFFSET/ORDER BY` query with a `LIKE` search in the store module (ADR-0011, ADR-0012); the shape below is unchanged, `app/grid_collection.py` became `app/grid.py`._

Large collections (transactions has 14k+ rows) are shown with AG Grid Community's Infinite Row
Model: the grid lazily requests blocks of rows from a server endpoint instead of loading
everything. Each grid page exposes a block datasource — `POST` taking `{startRow, endRow,
sortModel, q}` and returning `{rows, lastRow}` — backed by a Mongo `skip/limit/sort` query plus
a regex search.

We chose server-side paging because the row counts are too large to ship to the browser, and the
Community (free) tier's Infinite Row Model is enough — we don't need the enterprise Server-Side
Row Model's grouping/aggregation. Sorting and search are pushed to Mongo so the grid stays a thin
view.

_Consequence:_ the block/sort/search/serialize shape lives once in `app/grid_collection.py`
(GridCollection); each grid page is a declaration over it. The search regex only covers a
hand-picked set of text fields per collection (`search_cols`).
