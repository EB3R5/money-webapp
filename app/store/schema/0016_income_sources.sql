-- Income sources (ADR-0022): a row the person types to expect income the ledger cannot
-- detect — the Income category it lands in, a cadence, an amount and the anchor date of its
-- next occurrence (stepped by the calendar from there, never rewritten). The Planning pages
-- read active sources first and the detected Recurring series no source claims after them.
-- Deletes are audited to `deletions` (ADR-0005); inactive rows are kept for the record.
CREATE TABLE income_sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT,                  -- an Income Category name (categories.id); may be NULL
    cadence     TEXT NOT NULL,         -- weekly | biweekly | semimonthly | monthly | quarterly | yearly | irregular
    amount      REAL NOT NULL,         -- per occurrence, positive
    anchor_date TEXT,                  -- YYYY-MM-DD: the next occurrence when written
    active      INTEGER NOT NULL DEFAULT 1,
    notes       TEXT,
    created_at  TEXT,
    edited_at   TEXT
);
CREATE INDEX ix_income_sources_category ON income_sources(category);
