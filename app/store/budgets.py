"""Budgets — one row per budget version; its lines live in budget_lines (ADR-0012)."""

from .base import Field, Store

TABLE = 'budgets'

FIELDS = (
    Field('budgetId', 'budget_id', 'text'),
    Field('versionName', 'version_name', 'text'),
    Field('month', 'month', 'text'),
    Field('status', 'status', 'text'),
)

budgets = Store(TABLE, FIELDS)
