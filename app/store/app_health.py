"""App health — the one derived Data-health snapshot (id "current")."""

from .base import Field, Store

TABLE = 'app_health'

FIELDS = (
    Field('generated_at', 'generated_at', 'datetime'),
    Field('needs_categorization', 'needs_categorization', 'int'),
    Field('reports_current_through', 'reports_current_through', 'datetime'),
    Field('sections', 'sections', 'json'),
    Field('sync', 'sync', 'json'),
)

app_health = Store(TABLE, FIELDS)
