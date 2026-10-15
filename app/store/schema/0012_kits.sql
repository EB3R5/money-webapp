-- Kits (ADR-0018): a named set of Items and Software that serve one purpose — a view over
-- things already owned, with a description, a Markdown how-to and its own photos (`images`
-- is the photo entry list, files under DATA_DIR/photos/<id>/, as for inventory). A Kit has no
-- business id: the row id names it. Documents attach by (parent_table='kits', parent_id).
CREATE TABLE kits (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT,            -- one or two lines: the hero and the sidebar
    how_to       TEXT,            -- Markdown, rendered by documents.render_markdown
    images       TEXT,            -- JSON list of {id, filename, content_type}
    created_at   TEXT,
    edited_at    TEXT
);

-- One row per Kit member. The member is named polymorphically, (member_table, member_id),
-- as `documents` names its parent: an Item and a Software sit in one list and a member may
-- belong to several Kits. No SQL foreign key to the member (SQLite cannot point one column
-- at two tables): an Item's or Software's deletion removes its memberships in code, beside
-- the documents cascade. The kit side IS a foreign key: deleting a Kit drops its rows.
CREATE TABLE kit_members (
    id           TEXT PRIMARY KEY,
    kit_id       TEXT NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
    member_table TEXT NOT NULL,   -- inventory | software
    member_id    TEXT NOT NULL,   -- that table's row id (never Item_ID / SW_ID)
    position     INTEGER NOT NULL,-- order added: max(position) + 1 within the kit
    created_at   TEXT,
    edited_at    TEXT
);
CREATE UNIQUE INDEX ux_kit_members_member ON kit_members(kit_id, member_table, member_id);
CREATE INDEX ix_kit_members_member ON kit_members(member_table, member_id);
