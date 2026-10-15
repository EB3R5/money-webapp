"""Expected flows — typed money movements, income and planned spend (CONTEXT.md, ADR-0023).
app/expected_flows.py owns the conversion to a series, the calendar stepping, the merge with
detection and the registry rules; app/future_purchases.py writes the pulled rows."""

from .base import Field, Store

TABLE = "expected_flows"

FIELDS = (
    Field("kind", "kind", "text"),
    Field("name", "name", "text"),
    Field("category", "category", "text"),
    Field("group", "group", "text"),
    Field("cadence", "cadence", "text"),
    Field("amount", "amount", "real"),
    Field("anchor_date", "anchor_date", "date"),
    Field("day_known", "day_known", "bool"),
    Field("goal_id", "goal_id", "text"),
    Field("origin", "origin", "text"),
    Field("external_id", "external_id", "text"),
    Field("external_status", "external_status", "text"),
    Field("pulled", "pulled", "json"),
    Field("priority", "priority", "text"),
    Field("done_at", "done_at", "date"),
    Field("done_txn", "done_txn", "text"),
    Field("active", "active", "bool"),
    Field("notes", "notes", "text"),
)


class ExpectedFlowsStore(Store):
    def active(self, kind: str) -> list[dict]:
        return [f for f in self.list({"kind": kind}, order=[("name", "asc")]) if f.get("active", True)]

    def by_external_id(self, external_id: str) -> dict | None:
        return self.one({"external_id": external_id})

    def pulled(self) -> list[dict]:
        """Every row the Pull owns, active or not."""
        return self.list({"origin": "future-purchases"}, order=[("name", "asc")])


expected_flows = ExpectedFlowsStore(TABLE, FIELDS)
