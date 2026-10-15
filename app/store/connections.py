"""Connections — one row per SimpleFIN Bridge connection (a bank login); id is the conn_id."""

from .base import Field, Store

TABLE = 'connections'

FIELDS = (
    Field('conn_id', 'conn_id', 'text'),
    Field('name', 'name', 'text'),
    Field('org_id', 'org_id', 'text'),
    Field('org_url', 'org_url', 'text'),
    Field('sfin_url', 'sfin_url', 'text'),
    Field('last_seen_at', 'last_seen_at', 'datetime'),
)

connections = Store(TABLE, FIELDS)
