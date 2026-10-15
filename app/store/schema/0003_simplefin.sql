-- SimpleFIN feed (ADR-0014): connections, sync runs, the feed cursor, and provider columns
-- on the rows the feed writes. Money stays REAL (ADR-0012).

CREATE TABLE connections (
    id           TEXT PRIMARY KEY,      -- the Bridge conn_id
    conn_id      TEXT NOT NULL UNIQUE,
    name         TEXT,
    org_id       TEXT,
    org_url      TEXT,
    sfin_url     TEXT,
    last_seen_at TEXT,
    created_at   TEXT,
    edited_at    TEXT
);

CREATE TABLE sync_runs (
    id                    TEXT PRIMARY KEY,
    feed                  TEXT NOT NULL,      -- simplefin
    started_at            TEXT,
    finished_at           TEXT,
    status                TEXT CHECK (status IN ('running','ok','partial','failed','skipped_budget')),
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
    edited_at             TEXT
);
CREATE INDEX ix_sync_runs_started ON sync_runs(feed, started_at);

CREATE TABLE sync_cursors (
    id              TEXT PRIMARY KEY,         -- the feed name
    window_end      TEXT,
    last_success_at TEXT,
    created_at      TEXT,
    edited_at       TEXT
);

ALTER TABLE transactions ADD COLUMN source TEXT;
ALTER TABLE transactions ADD COLUMN provider_account_id TEXT;
ALTER TABLE transactions ADD COLUMN provider_txn_id TEXT;
ALTER TABLE transactions ADD COLUMN pending INTEGER;
ALTER TABLE transactions ADD COLUMN posted_at TEXT;
ALTER TABLE transactions ADD COLUMN last_seen_at TEXT;
-- A feed row's identity is (provider account, provider txn id); Tiller rows keep their own.
CREATE UNIQUE INDEX ux_transactions_provider
    ON transactions(provider_account_id, provider_txn_id) WHERE source = 'simplefin';
CREATE INDEX ix_transactions_pending ON transactions(provider_account_id, last_seen_at) WHERE pending = 1;

ALTER TABLE accounts ADD COLUMN simplefin_account_id TEXT;
ALTER TABLE accounts ADD COLUMN connection_id TEXT;
ALTER TABLE accounts ADD COLUMN currency TEXT;
ALTER TABLE accounts ADD COLUMN available REAL;
ALTER TABLE accounts ADD COLUMN balance_date TEXT;
ALTER TABLE accounts ADD COLUMN is_hidden INTEGER;
ALTER TABLE accounts ADD COLUMN last_seen_at TEXT;
CREATE UNIQUE INDEX ux_accounts_simplefin ON accounts(simplefin_account_id) WHERE simplefin_account_id IS NOT NULL;

ALTER TABLE balance_history ADD COLUMN sync_run_id TEXT;
ALTER TABLE balance_history ADD COLUMN available REAL;
CREATE UNIQUE INDEX ux_balance_history_run ON balance_history(account_id, sync_run_id) WHERE sync_run_id IS NOT NULL;
