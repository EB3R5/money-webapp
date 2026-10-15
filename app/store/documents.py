"""Documents — one row per file or note attached to a parent row (ADR-0016). The parent is
named by `(parent_table, parent_id)` so any collection can carry documents without a schema
change; `body` holds a text document's content and is left out of the list queries so a page
listing many parents stays cheap. The domain rules live in app/documents.py."""

from .base import Field, Store, q

TABLE = "documents"

FIELDS = (
    Field("parent_table", "parent_table"),
    Field("parent_id", "parent_id"),
    Field("name", "name"),
    Field("kind", "kind"),
    Field("content_type", "content_type"),
    Field("size", "size", "int"),
    Field("body", "body"),
    Field("file_ext", "file_ext"),
)

# Every column but `body` — what a list row carries.
LIST_COLUMNS = ("id", "parent_table", "parent_id", "name", "kind", "content_type",
                "size", "file_ext", "created_at", "edited_at")


class DocumentsStore(Store):
    def list_for_parents(self, parent_table: str, parent_ids) -> dict[str, list[dict]]:
        """{parent id: [rows without body]} in creation order, in one query."""
        ids = [str(i) for i in parent_ids]
        if not ids:
            return {}
        cols = ", ".join(q(c) for c in LIST_COLUMNS)
        marks = ", ".join("?" for _ in ids)
        rows = self.rows(
            f"SELECT {cols} FROM {q(self.table)} WHERE parent_table = ? AND parent_id IN ({marks}) "
            f"ORDER BY created_at, id", [parent_table, *ids])
        out: dict[str, list[dict]] = {}
        for r in rows:
            d = self.to_api(r)
            out.setdefault(d["parent_id"], []).append(d)
        return out

    def list_for_parent(self, parent_table: str, parent_id: str) -> list[dict]:
        return (self.list_for_parents(parent_table, [parent_id])).get(str(parent_id), [])


documents = DocumentsStore(TABLE, FIELDS)
