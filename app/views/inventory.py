"""Inventory — a CardCollection adapter. Active inventory items as clickable cards
grouped by Category, backed by the `inventory` store. The page is a keep_string page:
what you type is what is stored (the store types the numeric columns), and the only
numeric work is the derived Value (Qty × Unit_Cost). The card-grid + modal + dirty-diff +
create/delete + photo dance lives in app/card_collection.py; this file declares the
inventory-specific config (derived Value, create with auto Item_ID, delete-with-audit)."""

import secrets

from django.urls import path

from .. import web
from ..card_collection import CardCollection, CardField, plain
from ..store.inventory import inventory
from ..store.inventory_categories import inventory_categories
from ..inventory_item import FIELDS, SEARCH_FIELDS, value as _value


def _subtitle(d):
    base = d.get("Brand") or d.get("Subcategory") or d.get("Item_Type") or ""
    qty = plain(d.get("Qty"))
    suffix = " · ×" + str(qty) if (qty and str(qty) != "1") else ""
    return (base + suffix) or None


def _on_create(doc):
    doc.setdefault("Qty", "1")
    if not doc.get("Item_ID"):
        doc["Item_ID"] = "MAN-" + secrets.token_hex(3).upper()


_inventory = CardCollection(
    slug="inventory",
    store=inventory,
    id_field="Item_ID",
    title_field="Item_Name",
    group_by="Category",
    heading="Inventory",
    noun="items",
    item_noun="item",
    fields=[CardField(name, kind) for name, kind in FIELDS],
    amount=_value,
    subtitle=_subtitle,
    numeric_mode="keep_string",
    unclassified_label="(uncategorized)",
    show_grand=True,
    can_create=True,
    can_delete=True,
    on_create=_on_create,
    images_enabled=True,
    documents_enabled=True,
    kits_enabled=True,               # the Kits chips in the modal (ADR-0018)
    search_fields=SEARCH_FIELDS,
    # "Open sheet" → /inventory/{id}/sheet (views/inventory_export.py); the handler
    # lives in static/js/inventory.js. Only inventory has a sheet, hence per-collection.
    extra_actions=[{"id": "card-sheet", "label": "📄 Open sheet"}],
)

UNGROUPED = "(ungrouped)"


@web.GET
def inventory_taxonomy(request):
    """Category → Subcategory → Item_Type options for the modal's chained selects.
    Categories come from the inventoryCategories lookup (grouped by Group) plus any
    Category already used on an Item (under "(ungrouped)"); Subcategory / Item_Type
    values are whatever the Items already use, so the lists grow with the data."""
    groups: dict = {}
    tree: dict = {}
    for c in inventory_categories.list():
        cat = str(c.get("_id") or "").strip()
        if not cat:
            continue
        groups.setdefault(c.get("Group") or UNGROUPED, set()).add(cat)
        subs = tree.setdefault(cat, {})
        for s in str(c.get("Subcategory") or "").split(","):
            if s.strip():
                subs.setdefault(s.strip(), set())
    known = {cat for cats in groups.values() for cat in cats}
    for d in inventory.list():
        cat = str(d.get("Category") or "").strip()
        if not cat:
            continue
        if cat not in known:
            groups.setdefault(UNGROUPED, set()).add(cat)
            known.add(cat)
        subs = tree.setdefault(cat, {})
        sub = str(d.get("Subcategory") or "").strip()
        typ = str(d.get("Item_Type") or "").strip()
        if sub:
            types = subs.setdefault(sub, set())
            if typ:
                types.add(typ)
    key = lambda s: s.lower()  # noqa: E731
    return web.json({
        "groups": [{"name": g, "categories": sorted(groups[g], key=key)}
                   for g in sorted(groups, key=lambda g: (g == UNGROUPED, g.lower()))],
        "tree": {cat: {sub: sorted(types, key=key) for sub, types in sorted(subs.items(), key=lambda kv: kv[0].lower())}
                 for cat, subs in sorted(tree.items(), key=lambda kv: kv[0].lower())},
    })


# Before the board's /api/inventory/<doc_id>: Django matches by path, whatever the method.
urlpatterns = [
    path("api/inventory/taxonomy", inventory_taxonomy),
    *_inventory.urlpatterns(),
]
