"""Inventory — the Item sheet and the Item bundle export.

GET  /inventory/{doc_id}/sheet        read-only sheet for one Item (hero photo, headline,
                                      spec table, notes) with the Export button. Same-window
                                      navigation, because the desktop (pywebview) window
                                      has no tabs. Also the browser's print-to-PDF source.
POST /api/inventory/{doc_id}/export   multipart with an optional `png` (the sheet as the
                                      browser captured it) → the zip bundle.

The bundle itself is built by app/inventory_export.py from the row, the photo bytes (read
from the files beside the database — a photo whose file is gone is skipped, not fatal)
and the posted PNG."""

import logging
from datetime import UTC, datetime
from urllib.parse import quote

from django.http import HttpResponse
from django.urls import path

from .. import web
from ..inventory_export import bundle, sheet_context
from ..store.blobs import blobs
from ..store.inventory import inventory
from ..store.kit_members import kit_members
from .inventory import _inventory

log = logging.getLogger("money.inventory_export")


def _image_url(entry: dict) -> str:
    return f"/api/{_inventory.slug}/image/{entry['id']}"


@web.GET
def inventory_sheet(request, doc_id: str):
    doc = inventory.get(doc_id)
    if not doc:
        return HttpResponse("<h1>Item not found</h1>", status=404)
    urls = [_image_url(im) for im in (doc.get("_images") or []) if im.get("id")]
    return web.page(request, "inventory_sheet.html",
                    {"doc_id": doc_id, "sheet": sheet_context(doc, urls, _kits_of(doc_id))})


def _kits_of(doc_id: str) -> list:
    """The Kits this Item belongs to, by name (ADR-0018) — a sheet row and a front-matter list."""
    return (kit_members.list_for_members("inventory", [doc_id])).get(f"inventory:{doc_id}", [])


def _photos(doc: dict) -> list:
    """[(bytes, content_type, filename)] in stored order; a missing Blob is skipped."""
    out = []
    for im in doc.get("_images") or []:
        if not im.get("id"):
            continue
        got = blobs.get(im["id"], kind="photo")
        if got is None:
            log.warning("export: photo %s missing for item %s — skipped", im["id"], doc.get("_id"))
            continue
        data, ct = got
        out.append((data, im.get("content_type") or ct, im.get("filename")))
    return out


@web.POST
def inventory_export(request, doc_id: str):
    doc = inventory.get(doc_id)
    if not doc:
        return web.json({"ok": False, "error": "not found"}, 404)
    png = request.FILES.get("png")
    png_bytes = png.read() if png is not None else b""
    name, data = bundle(doc, _photos(doc), png_bytes or None, datetime.now(UTC),
                        _kits_of(doc_id))
    ascii_name = name.encode("ascii", "ignore").decode() or "item.zip"
    return HttpResponse(
        data, content_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}'})


urlpatterns = [
    path("inventory/<str:doc_id>/sheet", inventory_sheet),
    path("api/inventory/<str:doc_id>/export", inventory_export),
]
