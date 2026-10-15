"""Deletions — the audit log every hard delete writes first (ADR-0005). `collection` stays
the API key for the source table name so existing callers and the Data page read it unchanged."""

from datetime import UTC, datetime

from .base import Field, Store

TABLE = 'deletions'

FIELDS = (
    Field('collection', 'table', 'text'),
    Field('doc', 'doc', 'json'),
    Field('deleted_at', 'deleted_at', 'datetime'),
    Field('reason', 'reason', 'text'),
)


class DeletionsStore(Store):
    def log(self, collection: str, docs: list[dict], *, reason: str | None = None) -> None:
        """Snapshot API-shaped rows before they are removed from `collection`; `reason`
        names an automatic delete (pending_replaced, pending_vanished), NULL for a user's.
        The store-side twin of app/audit.py's log_deletions, for ported sections."""
        if not docs:
            return
        now = datetime.now(UTC)
        self.insert_many(
            {"collection": collection, "doc": d, "deleted_at": now, "reason": reason} for d in docs)


deletions = DeletionsStore(TABLE, FIELDS)
