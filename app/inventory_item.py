"""Inventory Item — the one statement of the Item schema its views share.

The card page (views/inventory.py) and the Finder-column page
(views/inventory_columns.py) render the same Items; before this module each restated
the field list and the Value rule, so adding a field meant editing both. The collection
name, the field list (name + input kind, in display order), and Value = Qty × Unit_Cost
(computed for display, never stored — see CONTEXT.md) live here instead. Items live in
the `inventory` store (numbers as REAL); `plain()` gives a stored 2.0 back as the 2 the
keep_string card page typed."""

from .card_collection import num0, plain

# (field, input kind) in display order. Color/Size/Dimensions/Link are app-owned
# enrichment, stored inline like Brand/Model/_images.
FIELDS = [
    ("Item_Name", "text"), ("Category", "text"), ("Subcategory", "text"),
    ("Item_Type", "text"), ("Brand", "text"), ("Model", "text"),
    ("Color", "text"), ("Size", "text"), ("Dimensions", "text"), ("Link", "text"),
    ("Qty", "number"), ("Unit_Cost", "number"),
    ("Salvage_Value", "number"), ("Useful_Life_Years", "number"),
    ("Classification", "text"), ("Source", "text"), ("Date_Moved", "text"),
    ("Notes", "textarea"),
]
FIELD_NAMES = [name for name, _kind in FIELDS]

# What a search reads (card board, Column view, clip picker; rule in app/search.py): every
# descriptive text field plus Item_ID. Link is left out: a URL matches noise tokens ("com",
# "dp") and the retailer is already in Source.
SEARCH_FIELDS = ["Item_ID"] + [name for name, kind in FIELDS if kind != "number" and name != "Link"]

# Accounting-only fields: kept in every export's data, left off the printed Item sheet.
SHEET_HIDDEN = ("Salvage_Value", "Useful_Life_Years", "Classification")


def value(d: dict) -> float:
    """Value of an Item: Qty × Unit_Cost over the source-typed strings."""
    return round(num0(d.get("Qty")) * num0(d.get("Unit_Cost")), 2)


def export_fields(d: dict) -> dict:
    """The exportable record of an Item: the declared fields in display order, blanks as
    "", plus the derived Value. Every export format (Markdown front matter today; CSV /
    JSON later) reads this so the field list is stated once — internals (_id, _images,
    _src, timestamps) never leak into an export."""
    out = {name: ("" if d.get(name) is None else str(plain(d.get(name)))) for name in FIELD_NAMES}
    out["Value"] = value(d)
    return out
