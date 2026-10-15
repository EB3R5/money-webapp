"""Accounts — holdings shown as cards; app-authored rows share the table with imported ones."""

from .base import Field, Store

TABLE = 'accounts'

FIELDS = (
    Field('Account ID', 'account_id', 'text'),
    Field('Account', 'account', 'text'),
    Field('Type', 'type', 'text'),
    Field('Group', 'group', 'text'),
    Field('Category', 'category', 'text'),
    Field('Amount', 'amount', 'real'),
    Field('Status', 'status', 'text'),
    Field('Account Type', 'account_type', 'text'),
    Field('Account Kind', 'account_kind', 'text'),
    Field('Institution', 'institution', 'text'),
    Field('APR %', 'apr_pct', 'real'),
    Field('Credit Limit', 'credit_limit', 'real'),
    Field('Min Payment', 'min_payment', 'real'),
    Field('Annual Fee', 'annual_fee', 'real'),
    Field('Opened Date', 'opened_date', 'date'),
    Field('Age (Last Date)', 'age_last_date', 'text'),
    Field('Time', 'time', 'text'),
    Field('Usage Notes', 'usage_notes', 'text'),
    # SimpleFIN feed (ADR-0014): provider identity and the provider-owned balance facts.
    Field('simplefin_account_id', 'simplefin_account_id', 'text'),
    Field('connection_id', 'connection_id', 'text'),
    Field('currency', 'currency', 'text'),
    Field('available', 'available', 'real'),
    Field('balance_date', 'balance_date', 'datetime'),
    Field('is_hidden', 'is_hidden', 'bool'),
    Field('last_seen_at', 'last_seen_at', 'datetime'),
)

accounts = Store(TABLE, FIELDS)
