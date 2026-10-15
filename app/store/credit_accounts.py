"""Credit accounts — the credit Registry; `_src` marks seeded vs hand-entered rows."""

from .base import Field, Store

TABLE = 'credit_accounts'

FIELDS = (
    Field('name', 'name', 'text'),
    Field('type', 'type', 'text'),
    Field('opened_date', 'opened_date', 'date'),
    Field('credit_limit', 'credit_limit', 'real'),
    Field('apr', 'apr', 'real'),
    Field('min_payment', 'min_payment', 'real'),
    Field('annual_fee', 'annual_fee', 'real'),
    Field('status', 'status', 'text'),
    Field('balance_account', 'balance_account', 'text'),
    Field('notes', 'notes', 'text'),
    Field('account_id', 'account_id', 'text'),   # the linked card's Account ID (Add-account fan-out)
    Field('_src', 'source', 'text'),
)

credit_accounts = Store(TABLE, FIELDS)
