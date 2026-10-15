"""Software clipper — HTTP adapter around app/software_clip.py (ADR-0017).

Pages
  GET  /software/clip           the popup the software bookmarklet opens (payload in the
                                URL fragment, never touches the server or its logs)

API (behind the session gate like every other /api route)
  POST /api/software/clip/prepare   {payload} → the registry's facts when the URL routes
                                    (GitHub, PyPI, npm, App Store, Homebrew), else what
                                    the bookmarklet harvested (OG + SoftwareApplication
                                    JSON-LD); the matching row (by Source_Key, then by
                                    normalised Link); the form fields; the stored-only
                                    facts; image candidates; the categories on the board
  GET  /api/software/items?q=       search picker (software_item.SEARCH_FIELDS)
  POST /api/software/{id}/fetch-image  {image_urls, referer} → attach to the row's gallery

Field writes go through the software board's own endpoints (POST /api/software/row,
POST /api/software/{id}); the registry-owned facts through POST /api/software/{id}/facts.
Registered BEFORE the board router: /api/software/clip/prepare would otherwise be
swallowed by POST /api/software/{doc_id}."""

import re

from django.urls import path

from .. import web
from ..inventory_clip import normalize_url
from ..software_clip import fetch_by_source_key, fetchable, fields_from_payload, route
from ..software_item import (CADENCES, FIELD_NAMES, KINDS, LICENSE_TYPES, SEARCH_FIELDS,
                             STORED_ONLY, WIRE, from_wire, source_key)
from ..store.software import software
from ..web import DomainError
from .inventory_clip import fetch_images, render_popup, search_items
from .software import _software

SOFTWARE_CLIP = {
    "slug": "software", "heading": "Software", "noun": "software item", "board_url": "/software",
    "idField": "SW_ID", "titleField": "Item_Name", "subtitleField": "Vendor",
    "search_placeholder": "Search by name, vendor, source key or ID…",
    "fields": [
        {"name": "Item_Name", "label": "Name", "kind": "text"},
        {"name": "Vendor", "label": "Vendor", "kind": "text"},
        {"name": "Kind", "label": "Kind", "kind": "select", "options": KINDS},
        {"name": "License_Type", "label": "License", "kind": "select", "options": LICENSE_TYPES},
        {"name": "Billing_Cadence", "label": "Billing", "kind": "select", "options": CADENCES},
        {"name": "Cost", "label": "Cost", "kind": "text"},
        {"name": "Version_Installed", "label": "Version", "kind": "text"},
        {"name": "Link", "label": "Link", "kind": "text"},
        {"name": "Source_Key", "label": "Source key", "kind": "text"},
        {"name": "Description", "label": "Description", "kind": "textarea"},
    ],
    "addRows": [{"name": "Notes", "kind": "textarea"}],
    "factsRoute": True,
}

# Wire keys whose stored field the modal never writes — they go through /facts.
_FACT_KEYS = {wk for wk, field in WIRE.items() if field in STORED_ONLY} | {"source_key"}


@web.GET
def clip_page(request):
    return render_popup(request, SOFTWARE_CLIP)


def prepare(payload: dict) -> dict:
    url = (payload.get("url") or "").strip() if isinstance(payload, dict) else ""
    if not re.match(r"^https?://", url):
        raise DomainError("a page URL is required")
    r = route(url)
    sk = source_key(*r) if r else None

    # The registry's facts win; what the bookmarklet harvested fills the gaps.
    wire = fields_from_payload(payload)
    images = [u for u in [payload.get("og_image"), wire.get("image_url")] if u]
    got = fetch_by_source_key(sk) if (r and fetchable(r[0])) else None
    if got:
        wire.update(got["fields"])
        if got.get("image_url"):
            images.insert(0, got["image_url"])
    wire["link"] = url
    if sk:
        wire["source_key"] = sk
    wire.pop("image_url", None)
    api = from_wire(wire)
    scraped = {k: v for k, v in api.items() if k in FIELD_NAMES}
    facts = {k: v for k, v in wire.items() if k in _FACT_KEYS}

    norm = normalize_url(url)
    found = []
    if sk:
        hit = software.one({"Source_Key": sk})
        if hit:
            found = [hit]
    by_link = []
    if not found:
        by_link = [d for d in software.list()
                   if d.get("Link") and normalize_url(d.get("Link") or "") == norm]
        by_link.sort(key=lambda d: str(d.get("Item_Name") or "").lower())
        found = by_link
    match = _software.serialize(found[0]) if found else None
    link_same = bool(match) and normalize_url(found[0].get("Link") or "") == norm

    names = sorted({c for c in software.distinct("Category") if c}, key=str.lower)
    suggested = api.get("Category") or None
    return {"ok": True, "scraped": scraped, "facts": facts, "source_key": sk,
            "images": list(dict.fromkeys(u for u in images if isinstance(u, str) and u.startswith("http"))),
            "match": match, "match_count": len(found), "link_same": link_same,
            "category": {"suggested": suggested, "candidates": []},
            "categories": [{"_id": n, "Group": ""} for n in names]}


@web.POST
def api_prepare(request):
    return web.json(prepare(web.read_json(request)))


@web.GET
def api_items(request):
    return web.json({"items": search_items(request.GET.get("q", ""), cc=_software, fields=SEARCH_FIELDS)})


@web.POST
def api_fetch_image(request, doc_id: str):
    return web.json(fetch_images(doc_id, web.read_json(request), cc=_software))


# /api/software/items precedes the board's /api/software/<doc_id> (app/urls.py order).
urlpatterns = [
    path("software/clip", clip_page),
    path("api/software/clip/prepare", api_prepare),
    path("api/software/items", api_items),
    path("api/software/<str:doc_id>/fetch-image", api_fetch_image),
]
