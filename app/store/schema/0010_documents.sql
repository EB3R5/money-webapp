-- Documents (ADR-0016): one row per file or note attached to a parent row. Text kinds (md,
-- txt) keep their content inline in `body`; every other kind is bytes on disk at
-- DATA_DIR/documents/<parent_table>/<parent_id>/<id>.<file_ext> and `body` is NULL.
CREATE TABLE documents (
    id            TEXT PRIMARY KEY,
    parent_table  TEXT NOT NULL,          -- the owning table, e.g. inventory
    parent_id     TEXT NOT NULL,          -- the owning row's id
    name          TEXT NOT NULL,          -- display name; the extension drives `kind`
    kind          TEXT NOT NULL,          -- md | txt | file
    content_type  TEXT,
    size          INTEGER NOT NULL DEFAULT 0,   -- bytes (UTF-8 length for text)
    body          TEXT,                   -- text kinds only
    file_ext      TEXT,                   -- file kind only: the on-disk extension
    created_at    TEXT,
    edited_at     TEXT
);
CREATE INDEX ix_documents_parent ON documents(parent_table, parent_id);
