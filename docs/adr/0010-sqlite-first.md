# The public repo is SQLite-first; data is carried over from Atlas once

_Status: the `photos/` part is superseded by ADR-0020 (2026-10-04) — photos and file Documents are rows of `blobs` inside the database; the one data directory, the SQLite-first rule and `models/` stand._

The app was built on MongoDB Atlas with Motor (ADR-0001). For the public, standalone repo it
becomes SQLite-first: one data directory (`DATA_DIR`, default `./data`) holding the database
file plus `photos/` and `models/` for what GridFS used to hold. A stranger's first run then
needs no external service: install, set a session secret, create the login, run. The data
model is the 24 entities kept by ADR-0008, no more.

The port is built in a private work repository (`money-webapp-next`, full history carried
over) while the Mongo version stays frozen in the original repository. The two run in parallel
as separate services (`money` on 8010, `money-next` on 8012, each with its own `.env`
and data); the SQLite build is seeded once from live Atlas and the two diverge from there.
Retiring the Mongo app, dropping the Atlas database, and archiving the frozen repository are a
later decision, not part of this port. The public repository is a third one, cut from the work
repository as a single squashed, gated commit once the port is done. A one-time export moves the real data from Atlas
into the SQLite schema, verified by the same census on both sides. The pre-trim Atlas dump
remains the permanent archive; trimming Atlas becomes moot. The SQLite build has no Mongo code
path: no dual backend inside one app.

Supersedes the Motor part of ADR-0001. What ADR-0001 said about keeping spreadsheet field
names is decided again for SQL in the schema ticket, not assumed.

_Consequence:_ every router's `db[...]` call, the mongomock test harness, the Data page, the
import kit's scratch-database rule (ADR-0009), and the backup runbook are reworked; each has
its own ticket on the wayfinder map.
