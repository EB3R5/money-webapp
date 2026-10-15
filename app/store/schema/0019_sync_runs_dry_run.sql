-- A dry-run sync is recorded like any run so its Bridge requests count toward the day's
-- budget; its row ends with status 'dry_run'. SQLite cannot alter a CHECK constraint, so the
-- table is rebuilt with the extended one (same columns as 0003 + 0009, same index).
CREATE TABLE sync_runs_new (
    id                    TEXT PRIMARY KEY,
    feed                  TEXT NOT NULL,      -- simplefin
    started_at            TEXT,
    finished_at           TEXT,
    status                TEXT CHECK (status IN ('running','ok','partial','failed','skipped_budget','dry_run')),
    trigger               TEXT CHECK (trigger IN ('scheduler','startup','manual','cli')),
    window_start          TEXT,
    window_end            TEXT,
    chunks                INTEGER,
    requests_used         INTEGER,
    accounts_seen         INTEGER,
    txns_new              INTEGER,
    txns_updated          INTEGER,
    txns_pending_replaced INTEGER,
    txns_pending_dropped  INTEGER,
    snapshots_added       INTEGER,
    errlist               TEXT,               -- JSON
    error                 TEXT,
    created_at            TEXT,
    edited_at             TEXT,
    rules_applied         INTEGER,
    ml_suggested          INTEGER
);
INSERT INTO sync_runs_new (id, feed, started_at, finished_at, status, trigger, window_start, window_end,
                           chunks, requests_used, accounts_seen, txns_new, txns_updated,
                           txns_pending_replaced, txns_pending_dropped, snapshots_added, errlist, error,
                           created_at, edited_at, rules_applied, ml_suggested)
    SELECT id, feed, started_at, finished_at, status, trigger, window_start, window_end,
           chunks, requests_used, accounts_seen, txns_new, txns_updated,
           txns_pending_replaced, txns_pending_dropped, snapshots_added, errlist, error,
           created_at, edited_at, rules_applied, ml_suggested
    FROM sync_runs;
DROP TABLE sync_runs;
ALTER TABLE sync_runs_new RENAME TO sync_runs;
CREATE INDEX ix_sync_runs_started ON sync_runs(feed, started_at);
