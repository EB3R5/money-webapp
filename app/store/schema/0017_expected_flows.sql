-- Expected flows (ADR-0023): the Income sources registry generalised to both signs. One row
-- per typed money movement — kind income or expense — with a cadence (once, weekly,
-- biweekly, semimonthly, monthly, bimonthly, quarterly, semiyearly, yearly, irregular), an
-- amount, the anchor date of its next occurrence (placed when set; a month-only placement
-- is the 1st with day_known = 0), a Category (income) or a ledger Group (expense), an
-- optional savings goal, and an origin: typed here or pulled from future-purchases, in
-- which case external_id is the item's business id and `pulled` snapshots what the feed
-- last said so a hand edit survives the next pull (ADR-0019's rule). A done flow keeps its
-- row. Deletes are audited to `deletions` (ADR-0005). Every income source is copied over.
CREATE TABLE expected_flows (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,                 -- income | expense
    name            TEXT NOT NULL,
    category        TEXT,                          -- income: the Category it lands in
    "group"         TEXT,                          -- expense: the ledger Group for the P&L
    cadence         TEXT NOT NULL,
    amount          REAL NOT NULL,                 -- per occurrence, positive
    anchor_date     TEXT,                          -- YYYY-MM-DD; NULL = unplaced
    day_known       INTEGER NOT NULL DEFAULT 1,    -- 0 = placed by month only
    goal_id         TEXT,                          -- savings_goals.id
    origin          TEXT NOT NULL DEFAULT 'typed', -- typed | future-purchases
    external_id     TEXT,                          -- RES-### / REC-### from future-purchases
    external_status TEXT,                          -- the item's status/state at the last pull
    pulled          TEXT,                          -- JSON: what the feed last said per field
    priority        TEXT,
    done_at         TEXT,                          -- YYYY-MM-DD when marked done
    done_txn        TEXT,                          -- reserved: the matching ledger row
    active          INTEGER NOT NULL DEFAULT 1,
    notes           TEXT,
    created_at      TEXT,
    edited_at       TEXT
);
CREATE INDEX ix_expected_flows_kind ON expected_flows(kind);
CREATE INDEX ix_expected_flows_category ON expected_flows(category);
CREATE INDEX ix_expected_flows_group ON expected_flows("group");
CREATE UNIQUE INDEX ux_expected_flows_external ON expected_flows(external_id) WHERE external_id IS NOT NULL;

INSERT INTO expected_flows (id, kind, name, category, cadence, amount, anchor_date, day_known,
                            origin, active, notes, created_at, edited_at)
SELECT id, 'income', name, category, cadence, amount, anchor_date, 1,
       'typed', active, notes, created_at, edited_at
FROM income_sources;

DROP TABLE income_sources;
