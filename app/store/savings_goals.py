"""Savings goals — the savings Registry."""

from .base import Field, Store

TABLE = 'savings_goals'

FIELDS = (
    Field('name', 'name', 'text'),
    Field('target_amount', 'target_amount', 'real'),
    Field('target_date', 'target_date', 'date'),
    Field('notes', 'notes', 'text'),
)

savings_goals = Store(TABLE, FIELDS, spill='data')
