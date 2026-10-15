"""Kits — a named set of Items and Software that serve one purpose (CONTEXT.md, ADR-0018).
`_images` is a JSON list of photo entries whose bytes are `blobs` rows keyed by the entry
id, as for inventory. Members are rows of `kit_members` (store/kit_members.py)."""

from .base import Field, Store

TABLE = "kits"

FIELDS = (
    Field("Name", "name", "text"),
    Field("Description", "description", "text"),
    Field("How_To", "how_to", "text"),
    Field("_images", "images", "json"),
)


class KitsStore(Store):
    pass


kits = KitsStore(TABLE, FIELDS)
