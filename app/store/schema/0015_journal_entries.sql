-- Journal entries (ADR-0021, D1): one row per period — "YYYY-MM" for a month, "YYYY" for a
-- year review — holding the Markdown body the Planning pages edit and the figures frozen
-- at first save (income, spend, net, net savings rate, Net worth and delta, budget version
-- and totals, biggest misses, the twelve-month net series). All three Planning pages read
-- and write the same row; Refreeze replaces `figures` on purpose. Hard deletes are audited
-- to `deletions` first (ADR-0005).
CREATE TABLE journal_entries (
    id         TEXT PRIMARY KEY,
    period     TEXT NOT NULL UNIQUE,   -- YYYY-MM or YYYY
    body       TEXT NOT NULL DEFAULT '',
    figures    TEXT,                   -- JSON, frozen at first save / refreeze
    frozen_at  TEXT,
    created_at TEXT,
    edited_at  TEXT
);
