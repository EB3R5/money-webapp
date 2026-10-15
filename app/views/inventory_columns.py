"""Inventory — Finder column (Miller-column) view. A second way to browse the same
Items as the card page (views/inventory.py),
drilling Group → Category → Subcategory → Item with a detail pane on the right, like
macOS Finder's column view.

Group comes from the inventoryCategories lookup (Category → Group, the taxonomy seeded by
scripts/import_inventory_categories.py); categories with no lookup row fall under
"(ungrouped)", and items with no Subcategory under "(none)". Only ~200 items, so the whole
tree is computed per request and returned as a single payload the JS renders into columns;
`?q=` filters the items with the shared search rule (app/search.py) before the counts and
values roll up, so the JS re-fetches as the user types.
"""

from django.urls import path

from .. import web
from ..card_collection import plain
from ..inventory_item import FIELD_NAMES as DETAIL_FIELDS, SEARCH_FIELDS, value as _item_value
from ..search import matches
from ..store.inventory import inventory
from ..store.inventory_categories import inventory_categories

UNGROUPED = "(ungrouped)"
NO_SUB = "(none)"


def _node(name):
    return {"name": name, "count": 0, "value": 0.0, "children": {}}


def _to_list(children, key):
    """Sorted child list; folders (Group/Category/Subcategory) alpha, leaves by name."""
    out = []
    for n in sorted(children.values(), key=lambda c: str(c["name"]).lower()):
        n["value"] = round(n["value"], 2)
        out.append({"name": n["name"], "count": n["count"], "value": n["value"],
                    key: _to_list(n["children"], key) if n["children"] else []})
    return out


@web.GET
def inventory_columns_page(request):
    return web.page(request, "inventory_columns.html", {"q": request.GET.get("q", "")})


@web.GET
def inventory_tree(request):
    q = request.GET.get("q", "")
    cat_group = {d["_id"]: (d.get("Group") or UNGROUPED) for d in inventory_categories.list()}

    root = {}
    grand_count, grand_value = 0, 0.0
    for d in inventory.list():
        name = (d.get("Item_Name") or "").strip()
        if not name or not matches(d, q, SEARCH_FIELDS):
            continue
        cat = (d.get("Category") or "").strip() or NO_SUB
        sub = (d.get("Subcategory") or "").strip() or NO_SUB
        grp = cat_group.get(cat, UNGROUPED)
        val = _item_value(d)
        grand_count += 1
        grand_value += val

        g = root.setdefault(grp, _node(grp))
        c = g["children"].setdefault(cat, _node(cat))
        s = c["children"].setdefault(sub, _node(sub))
        item = {"id": d.get("Item_ID") or str(d.get("_id")), "name": name, "value": val,
                "doc_id": str(d.get("_id")),   # the sheet route keys on the stored id
                "images": [im["id"] for im in (d.get("_images") or []) if im.get("id")],
                "fields": {f: plain(d.get(f)) for f in DETAIL_FIELDS if d.get(f) not in (None, "")}}
        item["fields"]["Value"] = val
        s["children"][item["id"]] = {"name": name, "count": 1, "value": val,
                                     "children": {}, "_item": item}
        for n in (g, c, s):
            n["count"] += 1
            n["value"] += val

    # Convert nested dicts → ordered lists; items carry their full detail payload.
    groups = []
    for g in sorted(root.values(), key=lambda c: str(c["name"]).lower()):
        cats = []
        for c in sorted(g["children"].values(), key=lambda c: str(c["name"]).lower()):
            subs = []
            for s in sorted(c["children"].values(), key=lambda c: str(c["name"]).lower()):
                items = [n["_item"] for n in sorted(
                    s["children"].values(), key=lambda c: str(c["name"]).lower())]
                subs.append({"name": s["name"], "count": s["count"],
                             "value": round(s["value"], 2), "items": items})
            cats.append({"name": c["name"], "count": c["count"],
                         "value": round(c["value"], 2), "subcategories": subs})
        groups.append({"name": g["name"], "count": g["count"],
                       "value": round(g["value"], 2), "categories": cats})

    return web.json({"groups": groups, "q": q,
                     "grand": {"count": grand_count, "value": round(grand_value, 2)}})


# /api/inventory/tree precedes the board's /api/inventory/<doc_id> (app/urls.py order).
urlpatterns = [
    path("inventory/columns", inventory_columns_page),
    path("api/inventory/tree", inventory_tree),
]
