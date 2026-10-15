"""Registry — the shared machinery behind the app-authored domain tables.

Credit, tax, savings, and health each keep a Config doc (one per-domain row in
`metrics_config`, merged over the domain's defaults on read) plus small registries of
manual rows (credit accounts, scores, activity; tax history; savings goals; health periods).
The config get/save merge, the uuid insert, the dirty-diff update, and the audited delete
had each been written per domain; the shared plumbing lives here. Domains still own their
field vocabulary and validation — they pass validated fields in.

Deletes snapshot to the deletions store first (ADR-0005). Updates set only the fields
passed in (ADR-0007)."""

import uuid

from .store.base import Store
from .store.deletions import deletions
from .store.metrics_config import metrics_config
from .web import DomainError


class ConfigDoc:
    """One domain's Config doc: read merges the stored row over `defaults` so a missing or
    partial doc still works; save writes the whole validated config."""

    def __init__(self, doc_id: str, defaults: dict):
        self.doc_id = doc_id
        self.defaults = defaults

    def get(self) -> dict:
        doc = metrics_config.get(self.doc_id) or {}
        cfg = dict(self.defaults)
        for k in self.defaults:
            if doc.get(k) is not None:
                cfg[k] = doc[k]
        return cfg

    def save(self, cfg: dict) -> dict:
        if metrics_config.get(self.doc_id) is None:
            metrics_config.insert({"_id": self.doc_id, **cfg})
        else:
            metrics_config.update(self.doc_id, cfg)
        return {"ok": True, "config": cfg}


def add_doc(store: Store, fields: dict) -> dict:
    """Insert validated fields as a new registry row with a uuid id."""
    _id = uuid.uuid4().hex
    store.insert({"_id": _id, **fields})
    return {"ok": True, "id": _id}


def update_doc(store: Store, _id, updates: dict, label: str = "item") -> dict:
    """Dirty-diff edit: set exactly `updates` (never untouched fields — ADR-0007)."""
    if not _id:
        raise DomainError("id is required")
    if store.get(_id) is None:
        raise DomainError(f"{label} not found", status=404)
    if updates:
        store.update(_id, updates)
    return {"ok": True}


def delete_doc(store: Store, _id, label: str = "item") -> dict:
    """Audited hard delete: snapshot to the deletions store (ADR-0005), then remove the row."""
    if not _id:
        raise DomainError("id is required")
    doc = store.get(_id)
    if not doc:
        raise DomainError(f"{label} not found", status=404)
    deletions.log(store.table, [doc])
    store.delete(_id)
    return {"ok": True, "deleted": 1}
