-- Uploads in the database (ADR-0020): the bytes of every photo (the `images` entries of
-- inventory, software and kits) and of every file Document, keyed by the photo entry id or
-- the documents row id, so money.sqlite alone holds what a person uploaded. The ML model
-- stays a file under models/. `data` is the last column so a metadata read (prune, census)
-- never pulls the overflow pages. A row outlives its owner on purpose (ADR-0005 addendum):
-- a row restored from `deletions` finds its bytes; scripts/prune_blobs.py removes the rest.
CREATE TABLE blobs (
    id           TEXT PRIMARY KEY,   -- photo entry id (uuid hex) or documents.id
    kind         TEXT NOT NULL,      -- photo | document
    content_type TEXT,
    size         INTEGER NOT NULL,
    sha256       TEXT NOT NULL,      -- the move script verifies it after insert
    created_at   TEXT,
    data         BLOB NOT NULL
);
