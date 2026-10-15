"""Sync runs — the full history of feed runs (SimpleFIN), one row per run with its counts."""

from .base import Field, Store

TABLE = 'sync_runs'

FIELDS = (
    Field('feed', 'feed', 'text'),
    Field('started_at', 'started_at', 'datetime'),
    Field('finished_at', 'finished_at', 'datetime'),
    Field('status', 'status', 'text'),
    Field('trigger', 'trigger', 'text'),
    Field('window_start', 'window_start', 'datetime'),
    Field('window_end', 'window_end', 'datetime'),
    Field('chunks', 'chunks', 'int'),
    Field('requests_used', 'requests_used', 'int'),
    Field('accounts_seen', 'accounts_seen', 'int'),
    Field('txns_new', 'txns_new', 'int'),
    Field('txns_updated', 'txns_updated', 'int'),
    Field('txns_pending_replaced', 'txns_pending_replaced', 'int'),
    Field('txns_pending_dropped', 'txns_pending_dropped', 'int'),
    Field('snapshots_added', 'snapshots_added', 'int'),
    Field('rules_applied', 'rules_applied', 'int'),     # new rows a Rule categorized
    Field('ml_suggested', 'ml_suggested', 'int'),       # new rows that received an ML suggestion
    Field('errlist', 'errlist', 'json'),
    Field('error', 'error', 'text'),
)


class SyncRunsStore(Store):
    def recent(self, feed: str | None = None, limit: int = 30) -> list[dict]:
        where = {"feed": feed} if feed else None
        return self.list(where, order=[("started_at", "desc")], limit=limit)


sync_runs = SyncRunsStore(TABLE, FIELDS)
