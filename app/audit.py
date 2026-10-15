"""Deletion audit log (ADR-0005). Hard deletes snapshot the rows into the deletions store
first so nothing is ever truly unrecoverable. Thin entry point over the deletions store."""

from .store.deletions import deletions


def log_deletions(collection: str, docs: list[dict]) -> None:
    """Snapshot rows into the deletions store before they are removed from `collection`."""
    deletions.log(collection, docs)
