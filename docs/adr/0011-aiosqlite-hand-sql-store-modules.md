# SQLite access layer: aiosqlite and hand-written SQL behind store modules

Supersedes ADR-0001. The app talks to SQLite through `aiosqlite` with hand-written SQL, no query
builder and no ORM. Every entity has a **store module** (`app/store/<entity>.py`) that owns its
SQL; routers and domain modules call store functions and never see a statement. The 16 Mongo
aggregation pipelines become plain `GROUP BY` queries inside the stores that own them (the
cashflow rollup keeps its single-owner rule). We chose this over SQLAlchemy Core because
nothing here needs portability, one small dependency beats a second syntax, and SQL a public
reader can read is part of the point.

Schema lives as numbered files, `app/store/schema/NNNN_<name>.sql`, applied in order at startup
against a `schema_version` table. Connections are opened per request or scheduler job, with
WAL journal mode, foreign keys on, and a `busy_timeout` of a few seconds; the database file is
`DATA_DIR/money.sqlite`, created on first start. The handle stays a module-level object in
`app/db.py` so the test suite's "no module keeps the production handle" sweep carries over.

The port is done on a long-lived `sqlite` branch in this repository: store modules with their
tests first, then routers section by section as pull requests into the branch, merged to `main`
only when the whole suite is green. No dual backend exists at any point.

_Consequence:_ the schema (column typing, names, JSON columns, ids) is a separate decision;
until it is made the store modules cannot be written.

_Addendum 2026-09-21 (tests):_ `app/db.py` exposes one `Database` object whose path comes from config; every module shares that object, so the test fixture re-points it at a fresh `DATA_DIR` under `tmp_path` and no `sys.modules` sweep is needed. Tests seed and assert through `tests/dbhelper.py`, which speaks API-shaped dicts and translates through the stores' field maps.

_Addendum 2026-10-08 (ADR-0024):_ the driver is the standard `sqlite3` module and every store call is synchronous; `scope()` / `acquire()` are plain context managers on the same context variable. Everything else here stands.
