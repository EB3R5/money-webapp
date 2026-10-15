"""Portfolio — Holdings (CONTEXT.md). Dollar and percent strings from the Sheets era are
REAL columns; Delta is a fraction."""

from .base import Field, Store

TABLE = 'portfolio'

FIELDS = (
    Field('Asset', 'asset', 'text'),
    Field('Group', 'group', 'text'),
    Field('Type', 'type', 'text'),
    Field('Category', 'category', 'text'),
    Field('Account', 'account', 'text'),
    Field('account_id', 'account_id', 'text'),
    Field('Current', 'current', 'text'),
    Field('Avg Cost', 'avg_cost', 'real'),
    Field('Shares', 'shares', 'real'),
    Field('Purchase Price', 'purchase_price', 'real'),
    Field('Current Price', 'current_price', 'real'),
    Field('Current Value', 'current_value', 'real'),
    Field('Return', 'return_value', 'real'),
    Field('Delta', 'delta', 'real'),
    Field('_price_updated_at', 'price_updated_at', 'datetime'),
    Field('_closed', 'closed', 'bool'),
)

portfolio = Store(TABLE, FIELDS)
