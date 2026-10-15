"""Categories — the fixed classification list; id is the Category name."""

from .base import Field, Store

TABLE = 'categories'

FIELDS = (
    Field('Category', 'category', 'text'),
    Field('Group', 'group', 'text'),
    Field('Type', 'type', 'text'),
    Field('Budget', 'budget', 'text'),
    Field('Cashflow Type', 'cashflow_type', 'text'),
    Field('Timing', 'timing', 'text'),
)

categories = Store(TABLE, FIELDS)
