"""Health periods — one row per Financial health period; inputs and scores spill into `data`."""

from .base import Field, Store

TABLE = 'health_periods'

FIELDS = (
    Field('period', 'period', 'text'),
)

health_periods = Store(TABLE, FIELDS, spill='data')
