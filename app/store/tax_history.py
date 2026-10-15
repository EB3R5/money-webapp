"""Tax history — one row per filed year; the open-ended fields spill into `data`."""

from .base import Field, Store

TABLE = 'tax_history'

FIELDS = (
    Field('tax_year', 'tax_year', 'int'),
)

tax_history = Store(TABLE, FIELDS, spill='data')
