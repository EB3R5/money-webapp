# The Sheets import kit depends on the app, never the reverse

_Status: moot since ADR-0015 (2026-09-24): the import kit and the Sheets helpers were removed with the Sheets path. The scratch-database rule had already been superseded by ADR-0013._

`migration/` is an optional, unpackaged import kit (discover, raw_load, transform, verify)
for building a database from Google Sheets. The Sheets helpers the running app also needs
(gspread client, backoff, value cleaning, header normalising, synthetic ids) live in
`app/sheets_io.py`; the kit imports them from there. Before this, `app/sheets_sync.py`
imported from `migration/`, so the Docker image and the wheel shipped a one-shot pipeline the
server never runs.

The kit writes raw mirrors only to a scratch database (ADR-0008). Promotion (`transform`) is
the one kit command that touches the app database: it reads raw from the scratch database and
upserts clean collections into the app database, both named explicitly on the command line,
and refuses when they are the same. `verify` reports on both sides.

_Consequence:_ a stranger can run the app without the kit, and run the kit against any text
file of spreadsheet links; the one-time sheet-sharing helper is gone and documented as a
manual step instead.
