"""Inventory categories — the Category/Subcategory/Item Type taxonomy for Items."""

from .base import Field, Store

TABLE = 'inventory_categories'

FIELDS = (
    Field('Category', 'category', 'text'),
    Field('Group', 'group', 'text'),
    Field('Subcategory', 'subcategory', 'text'),
    Field('Classification', 'classification', 'text'),
)

inventory_categories = Store(TABLE, FIELDS)
