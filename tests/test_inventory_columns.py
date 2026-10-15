"""Inventory column (Finder) view — the Group→Category→Subcategory→Item tree.
Uses the store-seeded inventory items (tests/dbhelper.py):
  inv1 Item_ID=X1  Drill  Category=Tools   Qty=2  Unit_Cost=50  Brand=Bosch  -> value 100
  inv2 Item_ID=X2  Pen    Category=Office  Qty=10 Unit_Cost=1                 -> value 10
Group comes from the inventoryCategories lookup, seeded per-test below.
"""

import pytest

from app.store.inventory import inventory
from app.store.inventory_categories import inventory_categories
from tests import dbhelper


@pytest.fixture
def inv_client(store_client):
    dbhelper.seed_inventory()
    return store_client


def _seed_groups(db=None):
    dbhelper.seed(inventory_categories, [
        {"_id": "Tools", "Category": "Tools", "Group": "Tools & Equipment"},
        {"_id": "Office", "Category": "Office", "Group": "Home"},
    ])


def test_page_renders(inv_client):
    r = inv_client.get("/inventory/columns")
    assert r.status_code == 200 and "Inventory — Columns" in r.text


def test_tree_groups_and_grand_totals(inv_client):
    _seed_groups()
    d = (inv_client.get("/api/inventory/tree")).json()
    assert d["grand"] == {"count": 2, "value": 110.0}        # 2*50 + 10*1
    assert [g["name"] for g in d["groups"]] == ["Home", "Tools & Equipment"]


def test_tree_drilldown_to_item_detail(inv_client):
    _seed_groups()
    d = (inv_client.get("/api/inventory/tree")).json()
    tools = next(g for g in d["groups"] if g["name"] == "Tools & Equipment")
    assert tools["count"] == 1 and tools["value"] == 100.0
    cat = tools["categories"][0]
    assert cat["name"] == "Tools"
    sub = cat["subcategories"][0]
    assert sub["name"] == "(none)"                            # no Subcategory on the item
    item = sub["items"][0]
    assert item["name"] == "Drill" and item["value"] == 100.0
    assert item["fields"]["Brand"] == "Bosch" and item["fields"]["Value"] == 100.0


def test_item_images_flow_into_tree(inv_client):
    _seed_groups()
    inventory.update("inv1", {"_images": [{"id": "img123", "filename": "drill.jpg", "content_type": "image/jpeg"}]})
    d = (inv_client.get("/api/inventory/tree")).json()
    tools = next(g for g in d["groups"] if g["name"] == "Tools & Equipment")
    item = tools["categories"][0]["subcategories"][0]["items"][0]
    assert item["images"] == ["img123"]


def test_enrichment_fields_editable_and_in_tree(inv_client):
    _seed_groups()
    # The card editor exposes the new enrichment fields.
    page = (inv_client.get("/inventory")).text
    for label in ("Color", "Size", "Dimensions", "Link"):
        assert label in page
    # And they flow through to the column-view detail payload.
    inventory.update("inv1", {"Color": "Blue", "Dimensions": "10x5x2", "Link": "https://example.com/drill"})
    d = (inv_client.get("/api/inventory/tree")).json()
    tools = next(g for g in d["groups"] if g["name"] == "Tools & Equipment")
    fields = tools["categories"][0]["subcategories"][0]["items"][0]["fields"]
    assert fields["Color"] == "Blue" and fields["Dimensions"] == "10x5x2"
    assert fields["Link"] == "https://example.com/drill"


def test_category_without_lookup_row_is_ungrouped(inv_client):
    # No inventoryCategories rows seeded → both items fall under "(ungrouped)".
    d = (inv_client.get("/api/inventory/tree")).json()
    assert [g["name"] for g in d["groups"]] == ["(ungrouped)"]
    assert d["groups"][0]["count"] == 2


# --- ?q= search (the shared rule, app/search.py) ------------------------------

def test_tree_q_filters_items_and_rolls_up(inv_client):
    _seed_groups()
    d = (inv_client.get("/api/inventory/tree?q=drill")).json()
    assert d["q"] == "drill" and d["grand"] == {"count": 1, "value": 100.0}
    assert [g["name"] for g in d["groups"]] == ["Tools & Equipment"]
    g = d["groups"][0]
    assert g["count"] == 1 and g["value"] == 100.0
    assert [i["name"] for i in g["categories"][0]["subcategories"][0]["items"]] == ["Drill"]


def test_tree_q_matches_item_id_case_insensitively(inv_client):
    d = (inv_client.get("/api/inventory/tree?q=X2")).json()
    assert d["grand"]["count"] == 1
    items = d["groups"][0]["categories"][0]["subcategories"][0]["items"]
    assert [i["id"] for i in items] == ["X2"]


def test_tree_q_every_word_must_match(inv_client):
    d = (inv_client.get("/api/inventory/tree?q=bosch pen")).json()
    assert d["groups"] == [] and d["grand"] == {"count": 0, "value": 0.0}
    full = (inv_client.get("/api/inventory/tree")).json()
    assert full["grand"]["count"] == 2 and full["q"] == ""


def test_page_renders_search_box_prefilled(inv_client):
    r = inv_client.get("/inventory/columns?q=pen")
    assert 'id="ic-q"' in r.text and 'value="pen"' in r.text
