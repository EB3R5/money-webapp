"""Budget lines — one row per Group in a budget version, in stored order."""

from .base import Field, Store

TABLE = 'budget_lines'

FIELDS = (
    Field('budget', 'budget_id', 'text'),
    Field('position', 'position', 'int'),
    Field('group', 'group', 'text'),
    Field('amount', 'amount', 'real'),
    Field('source', 'source', 'text'),
    Field('dataPoints', 'data_points', 'int'),
)

LINE_KEYS = ("group", "amount", "source", "dataPoints")


class BudgetLinesStore(Store):
    @staticmethod
    def as_line(row: dict) -> dict:
        """The embedded-line shape the editor, pivot, and report read."""
        return {k: row.get(k) for k in LINE_KEYS}

    def for_budget(self, budget_id: str) -> list[dict]:
        rows = self.list({"budget": budget_id}, order=[("position", "asc")])
        return [self.as_line(r) for r in rows]

    def by_budget(self) -> dict[str, list[dict]]:
        """{budget id: [line, …]} for every version, each in position order."""
        out: dict = {}
        for r in self.list(order=[("budget", "asc"), ("position", "asc")]):
            out.setdefault(r["budget"], []).append(self.as_line(r))
        return out


budget_lines = BudgetLinesStore(TABLE, FIELDS)
