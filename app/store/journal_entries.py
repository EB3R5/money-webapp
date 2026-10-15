"""Journal entries — one per period, shared by the three Planning pages (CONTEXT.md,
ADR-0021). `figures` is the JSON frozen at first save; app/planning.py owns its shape."""

from .base import Field, Store

TABLE = "journal_entries"

FIELDS = (
    Field("period", "period", "text"),
    Field("body", "body", "text"),
    Field("figures", "figures", "json"),
    Field("frozen_at", "frozen_at", "datetime"),
)


class JournalEntriesStore(Store):
    def for_period(self, period: str) -> dict | None:
        return self.one({"period": period})

    def periods_written(self) -> set[str]:
        """Every period with an entry — the Notebook rail's ✎ markers."""
        rows = self.rows(f"SELECT period FROM {TABLE}")
        return {r[0] for r in rows}


journal_entries = JournalEntriesStore(TABLE, FIELDS)
