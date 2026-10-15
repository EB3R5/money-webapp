"""Sync cursors — where each feed's window ended and when it last succeeded; id = feed."""

from .base import Field, Store

TABLE = 'sync_cursors'

FIELDS = (
    Field('window_end', 'window_end', 'datetime'),
    Field('last_success_at', 'last_success_at', 'datetime'),
)

sync_cursors = Store(TABLE, FIELDS)
