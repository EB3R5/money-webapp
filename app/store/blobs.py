"""Blobs — uploads in the database (ADR-0020). One row per photo (of an Item, a Software row
or a Kit) or per file Document, keyed by the id the owning row already carries: the photo
entry's `id` in its `_images` list, or the `documents` row id. `kind` keeps the two
namespaces apart so the image route never serves a Document and vice versa.

Hand SQL rather than a `Store` (base.py has no bytes kind). Writes go through the scope
connection, so a blob and the row that names it commit together in one request. A Blob
outlives its owner on purpose (ADR-0005 addendum): deleting one photo or one Document deletes
its Blob, deleting the owner does not; `scripts/prune_blobs.py` removes what nothing references.

The upload allow-list lives here too: `EXTENSIONS` is the raster content types a photo may
have (and the only kinds a Document shows inline as an image); `extension_for` and
`document_ext` give the cosmetic suffix a stored name carries."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from .database import database

KINDS = ("photo", "document")

EXTENSIONS = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/webp": "webp", "image/gif": "gif",
}
FALLBACK_EXT = "bin"
# What a photo's first bytes look like. A photo is admitted by its bytes, never by the type
# the client claims: an HTML or SVG page stored as a "photo" would be served inline on the
# app's origin otherwise.
_MAGIC = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png"),
          (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"))


def sniff_image(data: bytes) -> Optional[str]:
    """The raster type the bytes are, or None when they are not a JPEG, PNG, WebP or GIF."""
    head = bytes(data[:16] or b"")
    for magic, ct in _MAGIC:
        if head.startswith(magic):
            return ct
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EXT_OK = re.compile(r"^[a-z0-9]{1,10}$")

META_COLUMNS = "id, kind, content_type, size, sha256, created_at"


def _ct(content_type: Optional[str]) -> str:
    return (content_type or "application/octet-stream").split(";")[0].strip().lower()


def extension_for(content_type: Optional[str]) -> str:
    return EXTENSIONS.get((content_type or "").split(";")[0].strip().lower(), FALLBACK_EXT)


def document_ext(filename: Optional[str]) -> str:
    """The suffix a file Document records from its uploaded name: the lower-cased extension
    when that is a plain token, else `bin`. Cosmetic — serving uses the row's content type."""
    ext = Path(filename or "").suffix.lstrip(".").lower()
    return ext if _EXT_OK.match(ext) else FALLBACK_EXT


def _check_id(blob_id: str) -> str:
    if not isinstance(blob_id, str) or not _ID.match(blob_id):
        raise ValueError(f"unsafe blob id: {blob_id!r}")
    return blob_id


class BlobsStore:
    table = "blobs"

    def put(self, blob_id: str, kind: str, data: bytes,
                  content_type: Optional[str]) -> dict:
        """Insert bytes under `blob_id`; returns the row's metadata. Empty data, an unknown
        kind or an unsafe id raise ValueError; a duplicate id raises sqlite3.IntegrityError."""
        _check_id(blob_id)
        if kind not in KINDS:
            raise ValueError(f"unknown blob kind: {kind!r}")
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError("empty blob")
        data = bytes(data)
        meta = {"id": blob_id, "kind": kind, "content_type": _ct(content_type),
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "created_at": datetime.now(UTC).isoformat()}
        with database.acquire() as conn:
            conn.execute(
                "INSERT INTO blobs(id, kind, content_type, size, sha256, created_at, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (meta["id"], meta["kind"], meta["content_type"], meta["size"], meta["sha256"],
                 meta["created_at"], data))
        return meta

    def new_photo(self, data: bytes, content_type: Optional[str],
                        filename: Optional[str] = None) -> dict:
        """Store bytes as a new photo; returns the entry to append to a row's `_images`:
        `{id, filename, content_type}`, the filename falling back to `<id>.<ext>`. The type
        is what the bytes are (`sniff_image`); `content_type` is the client's claim and is
        ignored. Bytes that are not a JPEG, PNG, WebP or GIF raise ValueError."""
        sniffed = sniff_image(data)
        if sniffed is None:
            raise ValueError("not an image (JPEG, PNG, WebP or GIF)")
        content_type = sniffed
        blob_id = uuid.uuid4().hex
        meta = self.put(blob_id, "photo", data, content_type)
        return {"id": blob_id, "filename": filename or f"{blob_id}.{extension_for(content_type)}",
                "content_type": meta["content_type"]}

    def get(self, blob_id: str, kind: Optional[str] = None) -> Optional[tuple[bytes, str]]:
        """(bytes, content type) or None when no such blob (of that kind, when given)."""
        if not isinstance(blob_id, str) or not _ID.match(blob_id):
            return None
        sql, params = "SELECT data, content_type FROM blobs WHERE id = ?", [blob_id]
        if kind is not None:
            sql, params = sql + " AND kind = ?", params + [kind]
        with database.acquire() as conn:
            cur = conn.execute(sql, params)
            row = cur.fetchone()
        if row is None:
            return None
        return bytes(row[0]), row[1] or "application/octet-stream"

    def meta(self, blob_id: str) -> Optional[dict]:
        """The row without its bytes, or None."""
        if not isinstance(blob_id, str) or not _ID.match(blob_id):
            return None
        with database.acquire() as conn:
            cur = conn.execute(f"SELECT {META_COLUMNS} FROM blobs WHERE id = ?", [blob_id])
            row = cur.fetchone()
        return dict(row) if row is not None else None

    def delete(self, blob_id: str) -> bool:
        if not isinstance(blob_id, str) or not _ID.match(blob_id):
            return False
        with database.acquire() as conn:
            cur = conn.execute("DELETE FROM blobs WHERE id = ?", [blob_id])
            return cur.rowcount > 0

    def ids(self, kind: Optional[str] = None) -> list[str]:
        sql, params = "SELECT id FROM blobs", []
        if kind is not None:
            sql, params = sql + " WHERE kind = ?", [kind]
        with database.acquire() as conn:
            cur = conn.execute(sql + " ORDER BY id", params)
            return [r[0] for r in cur.fetchall()]

    def totals(self) -> dict:
        """{"photo": n, "document": n, "bytes": total size} — a metadata read."""
        out = {k: 0 for k in KINDS}
        out["bytes"] = 0
        with database.acquire() as conn:
            cur = conn.execute(
                "SELECT kind, COUNT(*), COALESCE(SUM(size), 0) FROM blobs GROUP BY kind")
            for kind, n, size in cur.fetchall():
                out[kind] = int(n)
                out["bytes"] += int(size)
        return out

    def referenced_ids(self) -> set[str]:
        """Every Blob id something still names: the live `_images` entries of inventory,
        software and kits, the live file Documents, and the same inside `deletions`
        snapshots (an owner's `_images`, a Document's `_id`) — those are the restorable ones
        (ADR-0005 addendum). One query; `json_each(NULL)` yields nothing, so a NULL column
        or a snapshot without `_images` needs no guard."""
        with database.acquire() as conn:
            cur = conn.execute(REFERENCED_SQL)
            return {r[0] for r in cur.fetchall() if r[0]}

    def unreferenced(self) -> list[dict]:
        """Metadata of every Blob no live row or deletion snapshot references, by id."""
        keep = self.referenced_ids()
        with database.acquire() as conn:
            cur = conn.execute(f"SELECT {META_COLUMNS} FROM blobs ORDER BY id")
            return [dict(r) for r in cur.fetchall() if r["id"] not in keep]


REFERENCED_SQL = """
SELECT json_extract(j.value, '$.id') FROM inventory, json_each(inventory.images) AS j
UNION SELECT json_extract(j.value, '$.id') FROM software, json_each(software.images) AS j
UNION SELECT json_extract(j.value, '$.id') FROM kits, json_each(kits.images) AS j
UNION SELECT id FROM documents WHERE kind = 'file'
UNION SELECT json_extract(j.value, '$.id')
      FROM deletions, json_each(json_extract(deletions.doc, '$._images')) AS j
      WHERE deletions."table" IN ('inventory', 'software', 'kits')
UNION SELECT json_extract(doc, '$._id') FROM deletions
      WHERE "table" = 'documents' AND json_extract(doc, '$.kind') NOT IN ('md', 'txt')
"""


blobs = BlobsStore()
