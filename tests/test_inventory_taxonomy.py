"""/api/inventory/taxonomy — the option tree behind the item modal's chained
Category → Subcategory → Item Type selects (app/static/js/inventory.js), read from the
inventory and inventory-categories stores."""

from app.store.inventory import inventory
from app.store.inventory_categories import inventory_categories
from tests import dbhelper


def test_taxonomy_groups_lookup_and_item_values(store_client):
    dbhelper.seed_inventory()
    dbhelper.seed(inventory_categories, [
        {"_id": "Tools", "Category": "Tools", "Group": "Workshop", "Subcategory": "Power Tools, Hand Tools"},
        {"_id": "Furniture", "Category": "Furniture", "Group": "Home"},
    ])
    dbhelper.seed(inventory, [
        {"_id": "i3", "Item_Name": "Saw", "Category": "Tools", "Subcategory": "Power Tools", "Item_Type": "Circular Saw"},
        {"_id": "i4", "Item_Name": "Hammer", "Category": "Tools", "Subcategory": "Hand Tools", "Item_Type": "Hammer"},
        {"_id": "i5", "Item_Name": "Tape", "Category": "Tools", "Subcategory": "Hand Tools", "Item_Type": "Measuring"},
        {"_id": "i6", "Item_Name": "Lamp", "Category": "Lighting", "Subcategory": "Desk", "Item_Type": ""},
        {"_id": "i7", "Item_Name": "Blank", "Category": "", "Subcategory": "x"},
    ])
    r = store_client.get("/api/inventory/taxonomy")
    assert r.status_code == 200
    d = r.json()
    # Lookup groups first (alpha), item-only categories last under (ungrouped).
    assert [g["name"] for g in d["groups"]] == ["Home", "Workshop", "(ungrouped)"]
    assert d["groups"][2]["categories"] == ["Lighting", "Office"]   # the seed's Pen is Category=Office
    assert d["groups"][1]["categories"] == ["Tools"]
    # Subcategories: lookup's comma list ∪ item values; Item_Types from items, sorted.
    assert d["tree"]["Tools"] == {"Hand Tools": ["Hammer", "Measuring"], "Power Tools": ["Circular Saw"]}
    assert d["tree"]["Lighting"] == {"Desk": []}
    assert "" not in d["tree"]


def test_taxonomy_empty_lookup(store_client):
    dbhelper.seed_inventory()
    r = store_client.get("/api/inventory/taxonomy")
    d = r.json()
    assert d["groups"] == [{"name": "(ungrouped)", "categories": ["Office", "Tools"]}]
    assert d["tree"] == {"Office": {}, "Tools": {}}


def test_taxonomy_route_registered():
    from app.views import inventory as inv_views
    from tests.dbhelper import routes
    paths = routes(inv_views)
    assert "/api/inventory/taxonomy" in paths
    assert paths.index("/api/inventory/taxonomy") < paths.index("/api/inventory/<str:doc_id>")
