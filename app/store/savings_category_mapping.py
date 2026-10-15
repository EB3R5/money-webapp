"""Savings category mapping — Savings_Role per ledger Category (app/category_mapping.py)."""

from .base import Field, Store

TABLE = 'savings_category_mapping'

FIELDS = (
    Field('Category', 'category', 'text'),
    Field('Group', 'group', 'text'),
    Field('Savings_Role', 'savings_role', 'text'),
    Field('Notes', 'notes', 'text'),
)

savings_category_mapping = Store(TABLE, FIELDS)
