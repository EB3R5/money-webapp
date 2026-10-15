"""Tax category mapping — tax_role and deduction fields per ledger Category."""

from .base import Field, Store

TABLE = 'tax_category_mapping'

FIELDS = (
    Field('Category', 'category', 'text'),
    Field('Group', 'group', 'text'),
    Field('tax_role', 'tax_role', 'text'),
    Field('deduction_type', 'deduction_type', 'text'),
    Field('schedule', 'schedule', 'text'),
    Field('notes', 'notes', 'text'),
)

tax_category_mapping = Store(TABLE, FIELDS)
