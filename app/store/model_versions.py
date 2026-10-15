"""Model versions — the pointer row for the ML categorizer file under DATA_DIR/models/."""

from .base import Field, Store

TABLE = 'model_versions'

FIELDS = (
    Field('name', 'name', 'text'),
    Field('path', 'path', 'text'),
    Field('sha256', 'sha256', 'text'),
    Field('sklearn_version', 'sklearn_version', 'text'),
    Field('trained_at', 'trained_at', 'text'),
    Field('rows_trained', 'rows_trained', 'int'),
    Field('n_categories', 'n_categories', 'int'),
    Field('filters_applied', 'filters_applied', 'json'),
    Field('source', 'source', 'text'),
)

model_versions = Store(TABLE, FIELDS)
