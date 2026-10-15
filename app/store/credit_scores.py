"""Credit scores — one row per bureau reading."""

from .base import Field, Store

TABLE = 'credit_scores'

FIELDS = (
    Field('date', 'date', 'date'),
    Field('bureau', 'bureau', 'text'),
    Field('score', 'score', 'int'),
    Field('change', 'change', 'real'),
    Field('notes', 'notes', 'text'),
    Field('_src', 'source', 'text'),
)

credit_scores = Store(TABLE, FIELDS)
