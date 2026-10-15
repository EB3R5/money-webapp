-- 0001_initial: the 24 app-owned entities plus support tables (ADR-0012).
-- Conventions: snake_case columns; id TEXT PRIMARY KEY (existing string ids kept, uuid4 for
-- new rows); REAL for money/quantities, INTEGER for counts and booleans, TEXT ISO-8601 for
-- dates and timestamps, TEXT holding JSON for nested values; created_at/edited_at everywhere.

CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Ledger ---------------------------------------------------------------------

CREATE TABLE transactions (
    id               TEXT PRIMARY KEY,
    transaction_id   TEXT,
    date             TEXT,
    description      TEXT,
    full_description TEXT,
    amount           REAL,
    account          TEXT,
    account_number   TEXT,
    institution      TEXT,
    month            TEXT,
    week             TEXT,
    category         TEXT,
    "group"          TEXT,
    budget           TEXT,
    cashflow_type    TEXT,
    timing           TEXT,
    type             TEXT,
    categorized_date TEXT,
    check_number     TEXT,
    metadata         TEXT,
    pred_category    TEXT,
    pred_conf        TEXT,      -- JSON
    created_at       TEXT,
    edited_at        TEXT
);
CREATE INDEX ix_transactions_date ON transactions(date);
CREATE INDEX ix_transactions_category ON transactions(category);
CREATE INDEX ix_transactions_account ON transactions(account);
-- Not unique: Tiller splits reuse ids like "split:[1]" and ~25% of rows have none.
CREATE INDEX ix_transactions_transaction_id ON transactions(transaction_id);

CREATE TABLE categories (
    id            TEXT PRIMARY KEY,   -- the Category name, as in the Mongo era
    category      TEXT NOT NULL,
    "group"       TEXT,
    type          TEXT,
    budget        TEXT,
    cashflow_type TEXT,
    timing        TEXT,
    created_at    TEXT,
    edited_at     TEXT
);

CREATE TABLE autocat (
    id                   TEXT PRIMARY KEY,
    category             TEXT NOT NULL,
    description_contains TEXT,
    account_contains     TEXT,
    institution_contains TEXT,
    amount_min           REAL,
    amount_max           REAL,
    created_at           TEXT,
    edited_at            TEXT
);

-- Accounts & balances --------------------------------------------------------

CREATE TABLE accounts (
    id            TEXT PRIMARY KEY,
    account_id    TEXT,
    account       TEXT,
    type          TEXT,
    "group"       TEXT,
    category      TEXT,
    amount        REAL,
    status        TEXT,
    account_type  TEXT,
    account_kind  TEXT,
    institution   TEXT,
    apr_pct       REAL,
    credit_limit  REAL,
    min_payment   REAL,
    annual_fee    REAL,
    opened_date   TEXT,
    age_last_date TEXT,
    time          TEXT,
    usage_notes   TEXT,
    created_at    TEXT,
    edited_at     TEXT
);
CREATE INDEX ix_accounts_account_id ON accounts(account_id);

CREATE TABLE balance_history (
    id             TEXT PRIMARY KEY,
    account_id     TEXT,
    account        TEXT,
    account_number TEXT,
    institution    TEXT,
    date           TEXT,
    balance        REAL,
    class          TEXT,
    "group"        TEXT,
    category       TEXT,
    type           TEXT,
    month          TEXT,
    week           TEXT,
    time           TEXT,
    "index"        TEXT,
    updated        TEXT,
    ml_confidence  TEXT,      -- free text in the sheet era
    ml_source      TEXT,
    source         TEXT,      -- snapshot source: portfolio_sync | inventory_sync | account_create | NULL
    created_at     TEXT,
    edited_at      TEXT
);
CREATE INDEX ix_balance_history_account_date ON balance_history(account_id, date);
CREATE INDEX ix_balance_history_date ON balance_history(date);

CREATE TABLE account_categories (
    id         TEXT PRIMARY KEY,
    category   TEXT NOT NULL,
    "group"    TEXT,
    type       TEXT,
    created_at TEXT,
    edited_at  TEXT
);

-- Inventory & investments ----------------------------------------------------

CREATE TABLE inventory (
    id                TEXT PRIMARY KEY,
    item_id           TEXT,
    item_name         TEXT,
    category          TEXT,
    subcategory       TEXT,
    item_type         TEXT,
    brand             TEXT,
    model             TEXT,
    color             TEXT,
    size              TEXT,
    dimensions        TEXT,
    link              TEXT,
    qty               REAL,
    unit_cost         REAL,
    salvage_value     REAL,
    useful_life_years REAL,
    classification    TEXT,
    source            TEXT,
    date_moved        TEXT,
    notes             TEXT,
    email_id          TEXT,
    images            TEXT,      -- JSON list of {id, filename, content_type}
    created_at        TEXT,
    edited_at         TEXT
);
CREATE INDEX ix_inventory_category ON inventory(category);

CREATE TABLE inventory_categories (
    id             TEXT PRIMARY KEY,
    category       TEXT NOT NULL,
    "group"        TEXT,
    subcategory    TEXT,
    classification TEXT,
    created_at     TEXT,
    edited_at      TEXT
);

CREATE TABLE portfolio (
    id               TEXT PRIMARY KEY,
    asset            TEXT,
    "group"          TEXT,
    type             TEXT,
    category         TEXT,
    account          TEXT,
    account_id       TEXT,
    current          TEXT,      -- a marker in the sheet era, not a number
    avg_cost         REAL,
    shares           REAL,
    purchase_price   REAL,
    current_price    REAL,
    current_value    REAL,
    return_value     REAL,
    delta            REAL,      -- percent points (-74.23 for the sheet's "-74.23%")
    price_updated_at TEXT,
    closed           INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT,
    edited_at        TEXT
);

-- Budgets --------------------------------------------------------------------

CREATE TABLE budgets (
    id           TEXT PRIMARY KEY,
    budget_id    TEXT,
    version_name TEXT,
    month        TEXT,      -- YYYY-MM
    status       TEXT,
    created_at   TEXT,
    edited_at    TEXT
);

CREATE TABLE budget_lines (
    id          TEXT PRIMARY KEY,
    budget_id   TEXT NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    "group"     TEXT NOT NULL,
    amount      REAL,
    source      TEXT,      -- historical | manual
    data_points INTEGER,
    created_at  TEXT,
    edited_at   TEXT
);
CREATE INDEX ix_budget_lines_budget ON budget_lines(budget_id, position);

-- Registries & mappings ------------------------------------------------------

CREATE TABLE credit_accounts (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    type            TEXT,
    opened_date     TEXT,
    credit_limit    REAL,
    apr             REAL,
    min_payment     REAL,
    annual_fee      REAL,
    status          TEXT,
    balance_account TEXT,
    notes           TEXT,
    source          TEXT,
    created_at      TEXT,
    edited_at       TEXT
);

CREATE TABLE credit_scores (
    id         TEXT PRIMARY KEY,
    date       TEXT,
    bureau     TEXT,
    score      INTEGER,
    change     REAL,
    notes      TEXT,
    source     TEXT,
    created_at TEXT,
    edited_at  TEXT
);

CREATE TABLE credit_activity (
    id         TEXT PRIMARY KEY,
    date       TEXT,
    category   TEXT,
    creditor   TEXT,
    bureau     TEXT,
    type       TEXT,
    amount     REAL,
    status     TEXT,
    result     TEXT,
    notes      TEXT,
    source     TEXT,
    created_at TEXT,
    edited_at  TEXT
);

CREATE TABLE savings_category_mapping (
    id           TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    "group"      TEXT,
    savings_role TEXT,
    notes        TEXT,
    created_at   TEXT,
    edited_at    TEXT
);

CREATE TABLE tax_category_mapping (
    id             TEXT PRIMARY KEY,
    category       TEXT NOT NULL,
    "group"        TEXT,
    tax_role       TEXT,
    deduction_type TEXT,
    schedule       TEXT,
    notes          TEXT,
    created_at     TEXT,
    edited_at      TEXT
);

-- Open-ended registries: a few fixed columns, the rest of the document in `data` (JSON).
CREATE TABLE tax_history (
    id         TEXT PRIMARY KEY,
    tax_year   INTEGER,
    data       TEXT,      -- JSON: the remaining fields
    created_at TEXT,
    edited_at  TEXT
);

CREATE TABLE savings_goals (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    target_amount REAL,
    target_date   TEXT,
    notes         TEXT,
    data          TEXT,
    created_at    TEXT,
    edited_at     TEXT
);

CREATE TABLE health_periods (
    id         TEXT PRIMARY KEY,
    period     TEXT,
    data       TEXT,      -- JSON: the input cells and computed scores
    created_at TEXT,
    edited_at  TEXT
);

CREATE TABLE metrics_config (
    id         TEXT PRIMARY KEY,   -- credit | tax | savings
    data       TEXT,               -- JSON: the domain's config doc
    created_at TEXT,
    edited_at  TEXT
);

-- App-owned singletons & logs ------------------------------------------------

CREATE TABLE users (
    id          TEXT PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    pw_hash     TEXT NOT NULL,
    totp_secret TEXT NOT NULL,
    created_at  TEXT,
    edited_at   TEXT
);

CREATE TABLE deletions (
    id         TEXT PRIMARY KEY,
    "table"    TEXT NOT NULL,   -- the table the row came from (API key: collection)
    doc        TEXT NOT NULL,   -- JSON snapshot of the row, API-shaped
    deleted_at TEXT NOT NULL,
    created_at TEXT,
    edited_at  TEXT
);
CREATE INDEX ix_deletions_table ON deletions("table", deleted_at);

CREATE TABLE model_versions (
    id              TEXT PRIMARY KEY,   -- the model name
    name            TEXT NOT NULL,
    path            TEXT,               -- relative to DATA_DIR, e.g. models/category_model-1a2b3c4d.joblib
    sha256          TEXT,
    sklearn_version TEXT,
    trained_at      TEXT,
    rows_trained    INTEGER,
    n_categories    INTEGER,
    filters_applied TEXT,               -- JSON
    source          TEXT,
    created_at      TEXT,
    edited_at       TEXT
);

CREATE TABLE app_health (
    id                      TEXT PRIMARY KEY,   -- "current"
    generated_at            TEXT,
    needs_categorization    INTEGER,
    reports_current_through TEXT,
    sections                TEXT,               -- JSON
    sync                    TEXT,               -- JSON
    created_at              TEXT,
    edited_at               TEXT
);

CREATE TABLE sync_state (
    id          TEXT PRIMARY KEY,   -- "last_run"
    started_at  TEXT,
    finished_at TEXT,
    duration_s  REAL,
    dry_run     INTEGER,
    results     TEXT,               -- JSON
    errors      TEXT,               -- JSON
    created_at  TEXT,
    edited_at   TEXT
);
