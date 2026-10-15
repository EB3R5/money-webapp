"""Autocat — Rule rows for the Rule engine (app/autocat.py): up to five conditions, the
Category they write, an explicit first-match-wins `order`, and an `enabled` flag."""

from typing import Optional

from .base import Field, Store

TABLE = 'autocat'

FIELDS = (
    Field('Category', 'category', 'text'),
    Field('Description Contains', 'description_contains', 'text'),
    Field('Account Contains', 'account_contains', 'text'),
    Field('Institution Contains', 'institution_contains', 'text'),
    Field('Amount Min', 'amount_min', 'real'),
    Field('Amount Max', 'amount_max', 'real'),
    Field('order', 'order', 'int'),
    Field('enabled', 'enabled', 'bool'),
)


class AutocatStore(Store):
    def in_order(self) -> list[dict]:
        """Every Rule, ordered: by `order`, then insertion order (rowid) for rows that have
        none yet — the engine's `ensure_order` assigns those."""
        rows = self.rows('SELECT * FROM autocat ORDER BY "order" IS NULL, "order", rowid')
        return [self.to_api(r) for r in rows]

    def unordered(self) -> list[dict]:
        """Rules with no `order` yet, in insertion order."""
        rows = self.rows('SELECT * FROM autocat WHERE "order" IS NULL ORDER BY rowid')
        return [self.to_api(r) for r in rows]

    def max_order(self) -> Optional[int]:
        rows = self.rows('SELECT MAX("order") FROM autocat')
        v = rows[0][0] if rows else None
        return int(v) if v is not None else None


autocat = AutocatStore(TABLE, FIELDS)
