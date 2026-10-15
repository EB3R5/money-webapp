"""Account categories — the balance-sheet lookup edited on the Categories page."""

from .base import Field, Store

TABLE = 'account_categories'

FIELDS = (
    Field('Category', 'category', 'text'),
    Field('Group', 'group', 'text'),
    Field('Type', 'type', 'text'),
)

account_categories = Store(TABLE, FIELDS)
