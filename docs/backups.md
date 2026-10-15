# Backups

Everything the app owns lives in one data directory (`DATA_DIR`, `./data` on the host,
`/app/data` in the image). This page says what a copy must hold and how to verify one.
When to take it, and where to keep it, is the host's business (`docs/deployment.md`).

## What a copy must hold

| Path | What it is | If lost |
|---|---|---|
| `money.sqlite` | Every row: transactions, balances, budgets, inventory, the planning journal, the audit log, the accounts and sessions — and, since ADR-0020, **every upload** (photos and file Documents are rows of `blobs`) | the data |
| `models/` | The categorizer's joblib file, named by its sha | one click: retrain on the Categorization page |

`-wal` and `-shm` files beside the database are SQLite's write-ahead log; a copy taken with
the backup API (below) folds them in. Nothing else under `DATA_DIR` matters.

## Taking a copy

Use SQLite's backup API, never a plain file copy of a database the app may be writing to:

```bash
sqlite3 data/money.sqlite ".backup '/path/to/money-$(date +%F).sqlite'"
cp -r data/models /path/to/models-$(date +%F)
```

This works while the app runs (the copy is transactionally consistent). From the reference
compose file: `docker compose exec money-next sqlite3 /app/data/money.sqlite ".backup
'/app/data/backup.sqlite'"`, then move the file out of the data directory. Any backup tool
that snapshots files (restic, borg, Time Machine) should back up the `.backup` output, not
the live file.

A copy of the database is the database: it holds the password hashes, the live sessions and
every transaction. Keep it on an encrypted volume and encrypt it before it leaves the machine.
`.env` (the session secret, the feed credential) is not in the data directory; back it up
separately and with the same care.

## Verifying a copy

A census counts rows and never prints one:

```bash
.venv/bin/python scripts/db_census.py --sqlite --data-dir data        --out before.json
.venv/bin/python scripts/db_census.py --sqlite --data-dir /path/to/copy --out after.json
.venv/bin/python scripts/db_census.py --diff before.json after.json      # exit 1 on a difference
```

(For the second run, put the copied database in a directory as `money.sqlite`.) In a healthy
census `photos.files` equals `photos.entries`, `documents.files` equals `documents.file_rows`,
and `blobs.unreferenced` is what `scripts/prune_blobs.py` would remove.

## Restoring

Restore into a **fresh** data directory, never over the live one: put the copy there as
`money.sqlite`, copy `models/` beside it, point `DATA_DIR` at it and start the app. The
start applies any schema files and migrations newer than the copy. The data directory is
treated as trusted code (`docs/SECURITY.md`, T13), so restore only a copy you made.
