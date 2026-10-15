"""Inventory clipper — HTTP adapter around app/inventory_clip.py.

Pages
  GET  /inventory/clip          the popup the bookmarklet opens (payload rides in the
                                URL fragment, never touches the server or its logs)
  (the bookmarklet is handed out on /clippers, app/views/clippers.py)

API (all behind the session gate like every other /api route)
  POST /api/inventory/clip/prepare   {payload} → normalised Item fields, the Item whose
                                     Link matches the page (if any), a Category
                                     suggestion, and the full category list
  GET  /api/inventory/items?q=       search picker (inventory_item.SEARCH_FIELDS, app/search.py)
  POST /api/inventory/{id}/fetch-image {image_urls:[...], referer} → download each and
                                     attach to the Item's photo gallery

Field writes deliberately go through the inventory board's own endpoints
(POST /api/inventory/row, POST /api/inventory/{id}) so whitelisting, Item_ID minting,
Qty defaults and dirty-diff semantics stay in one place (ADR-0007).

The popup page (clip.html + clip.js) and the picker / fetch-image operations are shared
with the software clipper (views/software_clip.py): `render_popup`, `search_items` and
`fetch_images` take the board they serve."""

import re

from django.urls import path
from django.views.generic import RedirectView

from .. import web
from ..image_fetch import download_image
from ..inventory_clip import image_candidates, normalize_url, scraped_fields, suggest_category
from ..inventory_item import SEARCH_FIELDS
from ..search import matches, tokens
from ..security import popup_csp
from ..store.inventory import inventory
from ..store.inventory_categories import inventory_categories
from ..web import DomainError
from .inventory import _inventory

MAX_IMAGES_PER_CALL = 8

# What clip.js needs to know about this board (rides as window.CLIP).
INVENTORY_CLIP = {
    "slug": "inventory", "heading": "Inventory", "noun": "Item", "board_url": "/inventory",
    "idField": "Item_ID", "titleField": "Item_Name", "subtitleField": "Brand",
    "search_placeholder": "Search by name, brand, model or ID…",
    "fields": [{"name": n, "label": l, "kind": "text"} for n, l in (
        ("Item_Name", "Name"), ("Brand", "Brand"), ("Model", "Model"), ("Unit_Cost", "Unit cost"),
        ("Color", "Color"), ("Size", "Size"), ("Dimensions", "Dimensions"), ("Link", "Link"),
        ("Source", "Source"))],
    "addRows": [{"name": "Qty", "value": "1", "kind": "text"}, {"name": "Notes", "kind": "textarea"}],
    "factsRoute": False,
}


# --- pages -------------------------------------------------------------------

def render_popup(request, cfg: dict):
    """The shared clip popup for one board. Carries its own CSP (route-owned) so the
    candidate images harvested off the clipped page can preview."""
    nonce = getattr(request, "csp_nonce", "")
    return web.page(request, "clip.html", {"cfg": cfg},
                    headers={"Content-Security-Policy": popup_csp(nonce)})


@web.GET
def clip_page(request):
    return render_popup(request, INVENTORY_CLIP)



# --- operations --------------------------------------------------------------

def _categories() -> list:
    cats = [{"_id": d["_id"], "Group": d.get("Group") or ""}
            for d in inventory_categories.list()]
    cats.sort(key=lambda c: ((c["Group"] or "~").lower(), str(c["_id"]).lower()))
    return cats


def prepare(payload: dict) -> dict:
    url = (payload.get("url") or "").strip() if isinstance(payload, dict) else ""
    if not re.match(r"^https?://", url):
        raise DomainError("a product URL is required")
    scraped = scraped_fields(payload)
    norm = normalize_url(url)

    matches = [d for d in inventory.list()
               if d.get("Link") and normalize_url(d.get("Link") or "") == norm]
    matches.sort(key=lambda d: str(d.get("Item_Name") or "").lower())
    match = _inventory.serialize(matches[0]) if matches else None

    cats = _categories()
    category = suggest_category(payload.get("category_hint"), payload.get("ld_category") or "",
                                [c["_id"] for c in cats])
    return {"ok": True, "scraped": scraped, "images": image_candidates(payload),
            "match": match, "match_count": len(matches),
            "link_same": bool(match),   # by construction: matched on the normalised Link
            "category": category, "categories": cats}


def search_items(q: str, limit: int = 20, *, cc=_inventory, fields=SEARCH_FIELDS) -> list:
    """The picker: the shared rule over the board's search fields; an empty query lists
    nothing. `cc` is the CardCollection whose store and serializer to use."""
    if not tokens(q):
        return []
    docs = [cc.serialize(d) for d in cc.store.list() if matches(d, q, fields)]
    docs.sort(key=lambda d: str(d.get(cc.title_field) or "").lower())
    return docs[:limit]


def fetch_images(doc_id: str, body: dict, *, cc=_inventory) -> dict:
    urls = body.get("image_urls")
    if not isinstance(urls, list):
        urls = [body.get("image_url")] if body.get("image_url") else []
    urls = [u.strip() for u in urls if isinstance(u, str) and re.match(r"^https?://", u.strip())]
    if not urls:
        raise DomainError("no image url")
    if cc.store.get(doc_id) is None:
        raise DomainError("item not found", status=404)
    referer = body.get("referer") if isinstance(body.get("referer"), str) else None

    results, attached = [], []
    for u in urls[:MAX_IMAGES_PER_CALL]:
        res = download_image(u, referer)
        if res.get("ok"):
            entry = cc.attach_image_bytes(
                doc_id, res["data"], res["content_type"], res["filename"])
            attached.append(entry)
            results.append({"url": u, "ok": True, "image": entry})
        else:
            results.append({"url": u, "ok": False, "error": res.get("error") or "failed"})
    errors = [r["error"] for r in results if not r["ok"]]
    return {"ok": bool(attached), "attached": len(attached), "images": attached,
            "results": results, "error": (errors[0] if errors and not attached else None)}


# --- routes ------------------------------------------------------------------

@web.POST
def api_prepare(request):
    return web.json(prepare(web.read_json(request)))


@web.GET
def api_items(request):
    return web.json({"items": search_items(request.GET.get("q", ""))})


@web.POST
def api_fetch_image(request, doc_id: str):
    return web.json(fetch_images(doc_id, web.read_json(request)))


# /api/inventory/items precedes the board's /api/inventory/<doc_id> (app/urls.py order).
urlpatterns = [
    path("inventory/clip", clip_page),
    path("inventory/clip/setup", RedirectView.as_view(url="/clippers", permanent=False)),   # moved to the Clippers page
    path("api/inventory/clip/prepare", api_prepare),
    path("api/inventory/items", api_items),
    path("api/inventory/<str:doc_id>/fetch-image", api_fetch_image),
]
