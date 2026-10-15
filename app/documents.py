"""Documents — the files and notes attached to a parent row (ADR-0016).

One row per attachment in `documents`, keyed by `(parent_table, parent_id)` so any
CardCollection can carry them. Two storage shapes behind one rule: text documents (`.md`,
`.txt`) are decoded and kept inline in `body` so they can be edited in-app; everything else
(images, PDFs, HTML, other binaries) is a Blob keyed by the document id (app/store/blobs.py,
ADR-0020) and the row keeps the uploaded name's suffix in `file_ext`. A note written in-app is
a Markdown document with an empty body.

Markdown is rendered server-side (markdown-it-py) and sanitized (nh3) before it is put on a
page. An uploaded HTML page is never inlined: the document page frames it in a sandboxed
iframe fed by the raw endpoint, which carries a sandbox CSP of its own, so the page gets an
opaque origin (no cookie, no API) even when opened directly. A PDF is framed for the
browser's viewer; a raster image is shown with <img>; anything else is a download.

Parents register themselves (`register_parent`) so the parent check, the back link, and the
page title need no import of the collection that owns the row."""

import html
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

import nh3
from markdown_it import MarkdownIt

from .config import UPLOAD_LIMIT_BYTES
from .store.blobs import EXTENSIONS as _IMAGE_TYPES, blobs, document_ext
from .store.base import Store
from .store.deletions import deletions
from .store.documents import documents as store
from .web import DomainError

TEXT_CAP = 1 * 1024 * 1024          # inline text documents
FILE_CAP = UPLOAD_LIMIT_BYTES       # file Documents (the multipart body limit)

TEXT_KINDS = {"md", "txt"}
_EXT_KIND = {".md": "md", ".markdown": "md", ".txt": "txt"}
_CT_KIND = {"text/markdown": "md", "text/plain": "txt"}
_KIND_CT = {"md": "text/markdown", "txt": "text/plain"}

_md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable("table").enable("strikethrough")


# --- parents ------------------------------------------------------------------------

@dataclass(frozen=True)
class Parent:
    store: Store
    title_field: str
    back_url: str
    noun: str


PARENTS: dict[str, Parent] = {}


def register_parent(table: str, *, store: Store, title_field: str, back_url: str, noun: str) -> None:
    """A collection that carries documents says how to find its rows and where to go back to."""
    PARENTS[table] = Parent(store, title_field, back_url, noun)


def _parent(parent_table: str, parent_id: str) -> dict:
    p = PARENTS.get(parent_table)
    row = p.store.get(parent_id) if (p and parent_id) else None
    if row is None:
        raise DomainError(f"{p.noun if p else parent_table} not found", status=404)
    return row


# --- pure rules --------------------------------------------------------------------

def classify(filename: str, content_type: str | None = None) -> str:
    """md | txt | file — by extension first, content type second."""
    ext = PurePosixPath(filename or "").suffix.lower()
    if ext in _EXT_KIND:
        return _EXT_KIND[ext]
    return _CT_KIND.get((content_type or "").split(";")[0].strip().lower(), "file")


def is_text_kind(kind: str | None) -> bool:
    return kind in TEXT_KINDS


def _ct(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def is_image(content_type: str | None) -> bool:
    """Only the raster allow-list photos use — never SVG, never a lying text/html."""
    return _ct(content_type) in _IMAGE_TYPES


def is_pdf(content_type: str | None) -> bool:
    return _ct(content_type) == "application/pdf"


def is_html(content_type: str | None) -> bool:
    return _ct(content_type) == "text/html"


def embed_kind(d: dict) -> str:
    """How a file document may be shown: html (sandboxed frame) | pdf (frame) | image |
    download. Decided from the stored content type; the extension never overrides it."""
    ct = d.get("content_type")
    if is_html(ct):
        return "html"
    if is_pdf(ct):
        return "pdf"
    if is_image(ct):
        return "image"
    return "download"


def render_markdown(body: str) -> str:
    """Markdown → sanitized HTML. Raw HTML inside the Markdown is allowed through the
    renderer and then cleaned, so tables/details survive but scripts never do."""
    return nh3.clean(_md.render(body or ""))


def render_text(body: str) -> str:
    """Plain text shown as typed: escaped, never interpreted."""
    return "<pre class=\"doc-plain\">" + html.escape(body or "") + "</pre>"


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DomainError("text document must be UTF-8")


def serialize(d: dict) -> dict:
    """Row for a parent's documents list (no body — that is the document page's)."""
    edited = d.get("_edited_at") or d.get("_created_at")
    kind = d.get("kind") or "file"
    return {"id": d["_id"], "parent_id": d.get("parent_id"), "name": d.get("name") or "(unnamed)",
            "kind": kind, "content_type": d.get("content_type") or "",
            "size": int(d.get("size") or 0),
            "edited_at": edited.isoformat() if isinstance(edited, datetime) else None,
            "is_image": is_image(d.get("content_type")), "editable": is_text_kind(kind)}


# --- operations ---------------------------------------------------------------------

def add_upload(parent_table: str, parent_id: str, filename: str,
                     content_type: str | None, data: bytes) -> dict:
    """Store one uploaded file under the text-inline / Blob rule."""
    _parent(parent_table, parent_id)
    if not data:
        raise DomainError(f"{filename or 'file'} is empty")
    kind = classify(filename, content_type)
    row = {"_id": uuid.uuid4().hex, "parent_table": parent_table, "parent_id": parent_id,
           "name": filename or "file", "kind": kind, "size": len(data)}
    if is_text_kind(kind):
        if len(data) > TEXT_CAP:
            raise DomainError(f"{filename} is over the {TEXT_CAP // (1024 * 1024)} MB text limit")
        row["content_type"] = _KIND_CT[kind]
        row["body"] = decode_text(data)
    else:
        if len(data) > FILE_CAP:
            raise DomainError(f"{filename} is over the {FILE_CAP // (1024 * 1024)} MB file limit")
        row["content_type"] = (content_type or "application/octet-stream").split(";")[0].strip().lower()
        row["file_ext"] = document_ext(filename)
        blobs.put(row["_id"], "document", data, row["content_type"])   # same scope as the row
    store.insert(row)
    return serialize(store.get(row["_id"]))


def add_note(parent_table: str, parent_id: str, name: str) -> dict:
    """A blank Markdown document written in-app."""
    _parent(parent_table, parent_id)
    name = (name or "").strip() or "Note"
    if not name.lower().endswith(".md"):
        name += ".md"
    doc_id = store.insert({"parent_table": parent_table, "parent_id": parent_id,
                                 "name": name, "kind": "md", "content_type": "text/markdown",
                                 "size": 0, "body": ""})
    return serialize(store.get(doc_id))


def list_for_parent(parent_table: str, parent_id: str) -> list:
    return [serialize(d) for d in store.list_for_parent(parent_table, parent_id)]


def get(doc_id: str) -> dict:
    d = store.get(doc_id) if doc_id else None
    if not d:
        raise DomainError("document not found", status=404)
    return d


def update(doc_id: str, updates: dict) -> dict:
    """Dirty-diff save (ADR-0007): only `name` and, for text documents, `body`."""
    d = get(doc_id)
    sets = {}
    if "name" in updates:
        name = (updates["name"] or "").strip()
        if not name:
            raise DomainError("name is required")
        sets["name"] = name
        sets["kind"] = classify(name, d.get("content_type")) if is_text_kind(d.get("kind")) else d.get("kind")
    if "body" in updates:
        if not is_text_kind(d.get("kind")):
            raise DomainError("only text documents can be edited")
        body = updates["body"] or ""
        if len(body.encode("utf-8")) > TEXT_CAP:
            raise DomainError(f"over the {TEXT_CAP // (1024 * 1024)} MB text limit")
        sets["body"] = body
        sets["size"] = len(body.encode("utf-8"))
    if sets:
        store.update(doc_id, sets)
    return {"ok": True, "document": serialize(store.get(doc_id))}


def delete(doc_id: str) -> dict:
    """Audit, remove the Blob (an already-missing one does not block), remove the row."""
    d = get(doc_id)
    deletions.log(store.table, [d])
    if not is_text_kind(d.get("kind")):
        blobs.delete(d["_id"])
    store.delete(doc_id)
    return {"ok": True, "deleted": 1}


def delete_for_parents(parent_table: str, parent_ids: list) -> None:
    """Parent delete cascade: audit and remove every document of the given parents. Their
    Blobs stay (ADR-0005 addendum) so a restored row gets them back."""
    ids = list(parent_ids)
    if not ids:
        return
    docs = store.list({"parent_table": parent_table, "parent_id": ids})
    if not docs:
        return
    deletions.log(store.table, docs)
    store.delete_where(_id=[d["_id"] for d in docs])


def raw(doc_id: str) -> tuple[bytes, str, str, str]:
    """(bytes, content type, filename, embed kind) for the raw endpoint. Text documents are
    always a download (`embed_kind` "download"); the browser must not render a .md as HTML."""
    d = get(doc_id)
    ct = d.get("content_type") or "application/octet-stream"
    if is_text_kind(d.get("kind")):
        return (d.get("body") or "").encode("utf-8"), ct, d["name"], "download"
    got = blobs.get(d["_id"], kind="document")
    if got is None:
        raise DomainError("file is missing from storage", status=404)
    return got[0], ct, d["name"], embed_kind(d)


def page_context(d: dict) -> dict:
    """View-model for the document page: what to show and whether it can be edited."""
    kind = d.get("kind") or "file"
    html = ""
    if kind == "md":
        html = render_markdown(d.get("body") or "")
    elif kind == "txt":
        html = render_text(d.get("body") or "")
    p = PARENTS.get(d.get("parent_table") or "")
    parent = p.store.get(d.get("parent_id")) if p else None
    raw_url = f"/api/documents/{d['_id']}/raw"
    return {**serialize(d), "body": d.get("body") if is_text_kind(kind) else None,
            "html": html, "editable": is_text_kind(kind),
            "parent_title": (parent or {}).get(p.title_field) if p else None,
            "back_url": p.back_url if p else "/",
            "raw_url": raw_url, "download_url": raw_url + "?download=1",
            "show": "inline" if html else embed_kind(d)}
