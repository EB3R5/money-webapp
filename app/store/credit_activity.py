"""Credit activity — applications, inquiries, and outcomes."""

from .base import Field, Store

TABLE = 'credit_activity'

FIELDS = (
    Field('date', 'date', 'date'),
    Field('category', 'category', 'text'),
    Field('creditor', 'creditor', 'text'),
    Field('bureau', 'bureau', 'text'),
    Field('type', 'type', 'text'),
    Field('amount', 'amount', 'real'),
    Field('status', 'status', 'text'),
    Field('result', 'result', 'text'),
    Field('notes', 'notes', 'text'),
    Field('_src', 'source', 'text'),
)

credit_activity = Store(TABLE, FIELDS)
