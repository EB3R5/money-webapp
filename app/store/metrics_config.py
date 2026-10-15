"""Metrics config — one Config doc per domain (credit, tax, savings), the whole doc in `data`."""

from .base import Field, Store

TABLE = 'metrics_config'

FIELDS = (
)

metrics_config = Store(TABLE, FIELDS, spill='data')
