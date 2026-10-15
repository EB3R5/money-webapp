"""Inventory clipper — the pure normalizers (app/inventory_clip.py) and the HTTP surface
(app/views/inventory_clip.py). Field writes are the board's own endpoints, already
covered in test_card_collection.py; here we pin the clip-specific pieces: URL matching,
price/dimension parsing, category suggestion, the bookmarklet's shape, search, prepare,
and image attach with the download stubbed."""

import pytest

from app.inventory_clip import (bookmarklet, format_dimensions, image_candidates,
                                normalize_url, scraped_fields, suggest_category, to_cost_str)
from app.inventory_item import FIELD_NAMES
from app.store.blobs import blobs
from app.store.inventory import inventory
from app.store.inventory_categories import inventory_categories
from tests import dbhelper


@pytest.fixture
def inv_client(store_client):
    dbhelper.seed_inventory()
    return store_client

# --- normalize_url --------------------------------------------------------------------

@pytest.mark.parametrize("a, b", [
    ("https://www.example.com/drill?utm_source=x&ref=abc#top", "https://example.com/drill"),
    ("HTTPS://Example.com/drill/", "https://example.com/drill"),
    ("https://shop.test/p/1?variant=2&utm_medium=m", "https://shop.test/p/1?variant=2"),
    ("https://shop.test/p/1?b=2&a=1", "https://shop.test/p/1?a=1&b=2"),
    ("https://www.amazon.com/Some-Long-Title/dp/B0ABCDEF12/ref=sr_1_3?keywords=x&th=1&psc=1",
     "https://amazon.com/dp/B0ABCDEF12"),
    ("https://www.amazon.de/gp/product/B0ABCDEF12?tag=foo", "https://amazon.de/dp/B0ABCDEF12"),
])
def test_normalize_url(a, b):
    assert normalize_url(a) == b


def test_normalize_url_garbage():
    assert normalize_url("") == ""
    assert normalize_url("not a url") == ""
    assert normalize_url(None) == ""


# --- to_cost_str ----------------------------------------------------------------------

@pytest.mark.parametrize("raw, out", [
    ("$1,234.56", "1234.56"), ("59,99 €", "59.99"), ("1.234,56", "1234.56"), ("1,234", "1234"),
    ("1.234", "1234"), ("59.99", "59.99"), ("€ 12", "12"), (12, "12"), (12.5, "12.50"),
    ("1,5", "1.50"), ("abc", ""), ("", ""), (None, ""), ("299.00", "299"), ("2 499 kr", "2499"),
])
def test_to_cost_str(raw, out):
    assert to_cost_str(raw) == out


# --- format_dimensions ----------------------------------------------------------------

def test_dimensions_from_structured_ld():
    dims = {"width": {"value": "80", "unit": "CMT"}, "depth": {"value": 28, "unit": "CMT"},
            "height": {"value": "202", "unit": "CMT"}}
    assert format_dimensions(dims) == "80×28×202 cm"


def test_dimensions_partial_and_weight():
    dims = {"width": {"value": "80 cm", "unit": ""}, "height": {"value": "202 cm", "unit": ""},
            "weight": {"value": "12.5", "unit": "kg"}}
    assert format_dimensions(dims) == "W 80 cm · H 202 cm · 12.5 kg"


def test_dimensions_fractional_inches():
    dims = {"width": {"value": '31 1/2 "', "unit": ""}, "depth": {"value": '11 "', "unit": ""},
            "height": {"value": '79 1/2 "', "unit": ""}}
    assert format_dimensions(dims) == "31.5×11×79.5 in"


def test_dimensions_from_amazon_raw():
    assert format_dimensions({}, '10 x 5.5 x 2 inches') == "10×5.5×2 in"
    assert format_dimensions({}, "  something   odd ") == "something odd"
    assert format_dimensions(None, "") == ""


# --- suggest_category -----------------------------------------------------------------

CATS = ["Furniture", "Tools", "Kitchen Appliances", "Kitchen Appliance", "Sports & Fitness", "Art"]


def test_suggest_category_breadcrumb_specific_first():
    r = suggest_category(["Home", "Furniture", "Bookcases"], "", CATS)
    assert r["suggested"] == "Furniture"


def test_suggest_category_exact_beats_fuzzy_on_near_duplicates():
    r = suggest_category(["Kitchen appliances"], "", CATS)
    assert r["suggested"] == "Kitchen Appliances"
    assert "Kitchen Appliance" in r["candidates"]


def test_suggest_category_ld_path_and_fuzzy():
    r = suggest_category([], "Home > Power Tools", CATS)
    assert r["suggested"] == "Tools"
    r = suggest_category([], "Sport", CATS)
    assert r["suggested"] == "Sports & Fitness"


def test_suggest_category_nothing():
    assert suggest_category(["Zzzz"], "", CATS) == {"suggested": None, "candidates": []}
    assert suggest_category(["Tools"], "", []) == {"suggested": None, "candidates": []}
    # short/generic hints never match a short category by substring ("Art" in "Party")
    assert suggest_category(["Party"], "", CATS)["suggested"] is None


# --- scraped_fields / image_candidates --------------------------------------------------

PAYLOAD = {
    "url": "https://www.ikea.com/us/en/p/billy-bookcase-white-00263850/?utm_source=x",
    "domain": "www.ikea.com", "item_name": "  BILLY  Bookcase ", "brand": "IKEA", "model": "",
    "sku": "00263850", "price": "$59.99", "currency": "USD", "color": "white", "size": "",
    "dimensions_raw": "", "dims": {"width": {"value": "31 1/2", "unit": ""}},
    "images": ["https://img.test/a.jpg", "https://img.test/a.jpg", "//img.test/b.jpg", "x"],
    "category_hint": ["Products", "Furniture", "Bookcases"], "ld_category": "",
}


def test_scraped_fields_shape():
    f = scraped_fields(PAYLOAD)
    assert set(f) <= set(FIELD_NAMES)
    assert f["Item_Name"] == "BILLY Bookcase"
    assert f["Model"] == "00263850"           # sku fallback
    assert f["Unit_Cost"] == "59.99"
    assert f["Link"] == PAYLOAD["url"]        # original url, not normalised
    assert f["Source"] == "ikea.com"
    assert f["Color"] == "white"
    assert "image_url" not in f and "images" not in f


def test_image_candidates_dedup_and_http_only():
    assert image_candidates(PAYLOAD) == ["https://img.test/a.jpg"]


# --- bookmarklet ----------------------------------------------------------------------

def test_bookmarklet_shape():
    js = bookmarklet("http://127.0.0.1:8010/")
    assert js.startswith("javascript:(function(){")
    assert "\n" not in js and '"' not in js
    assert "'127.0.0.1:8010'" in js                      # self-guard host
    assert "http://127.0.0.1:8010/inventory/clip#" in js  # popup target
    assert "application/ld+json" in js and "og:title" in js


def test_bookmarklet_store_rules_are_host_gated():
    js = bookmarklet("http://127.0.0.1:8010")
    amazon = js.index("indexOf('amazon.')")
    ikea = js.index("indexOf('ikea.')")
    assert js.index("#productTitle") > amazon
    assert js.index("#corePriceDisplay_desktop_feature_div") > amazon
    assert js.index("data-a-dynamic-image") > amazon
    assert js.index("pip-product-dimensions") > ikea
    assert js.index("f=xl") > ikea


# --- routes ---------------------------------------------------------------------------

def test_pages_render(inv_client):
    r = inv_client.get("/inventory/clip")
    assert r.status_code == 200 and "clip-table" in r.text
    r = inv_client.get("/inventory/clip/setup")
    assert r.status_code == 302 and r.headers["location"] == "/clippers"   # moved to the Clippers page


def test_search_items(inv_client):
    r = inv_client.get("/api/inventory/items?q=drill")
    assert [i["Item_ID"] for i in r.json()["items"]] == ["X1"]
    r = inv_client.get("/api/inventory/items?q=bosch")
    assert [i["Item_ID"] for i in r.json()["items"]] == ["X1"]
    r = inv_client.get("/api/inventory/items?q=x2")
    assert [i["Item_ID"] for i in r.json()["items"]] == ["X2"]
    r = inv_client.get("/api/inventory/items?q=bosch pen")
    assert r.json()["items"] == []
    r = inv_client.get("/api/inventory/items?q=")
    assert r.json()["items"] == []


def test_prepare_matches_on_normalised_link(inv_client):
    inventory.update("inv1", {"Link": "https://www.example.com/drill?utm_source=x"})
    dbhelper.seed(inventory_categories, [
        {"_id": "Tools", "Category": "Tools", "Group": "Workshop"},
        {"_id": "Office", "Category": "Office", "Group": "Home"}])
    body = dict(PAYLOAD, url="https://example.com/drill/#top", category_hint=["Home", "Power Tools"])
    r = inv_client.post("/api/inventory/clip/prepare", json=body)
    d = r.json()
    assert d["ok"] and d["match"]["_id"] == "inv1" and d["match_count"] == 1 and d["link_same"]
    assert d["match"]["Item_ID"] == "X1" and "_images" in d["match"]
    assert d["scraped"]["Source"] == "example.com"
    assert d["category"]["suggested"] == "Tools"
    assert [c["_id"] for c in d["categories"]] == ["Office", "Tools"]   # grouped, sorted
    assert d["images"] == ["https://img.test/a.jpg"]


def test_prepare_no_match_and_bad_url(inv_client):
    r = inv_client.post("/api/inventory/clip/prepare", json=PAYLOAD)
    d = r.json()
    assert d["ok"] and d["match"] is None and d["match_count"] == 0 and not d["link_same"]
    assert d["category"] == {"suggested": None, "candidates": []}
    r = inv_client.post("/api/inventory/clip/prepare", json={"url": "nope"})
    assert r.status_code == 400 and r.json()["ok"] is False


def test_fetch_image_attaches(inv_client, monkeypatch):
    calls = []

    def fake(url, referer=None):
        calls.append((url, referer))
        if url.endswith("bad.jpg"):
            return {"ok": False, "error": "image fetch returned HTTP 403"}
        return {"ok": True, "data": b"\x89PNGDATA", "content_type": "image/png", "filename": "a.png"}
    monkeypatch.setattr("app.views.inventory_clip.download_image", fake)

    r = inv_client.post("/api/inventory/inv1/fetch-image", json={
        "image_urls": ["https://img.test/a.png", "https://img.test/bad.jpg"],
        "referer": "https://example.com/drill"})
    d = r.json()
    assert d["ok"] and d["attached"] == 1 and d["images"][0]["filename"] == "a.png"
    assert [x["ok"] for x in d["results"]] == [True, False]
    assert d["results"][1]["error"] == "image fetch returned HTTP 403"
    assert calls[0] == ("https://img.test/a.png", "https://example.com/drill")
    doc = inventory.get("inv1")
    assert len(doc["_images"]) == 1 and doc["_images"][0]["content_type"] == "image/png"
    assert doc["_edited_at"]
    assert blobs.get(doc["_images"][0]["id"], kind="photo") == (b"\x89PNGDATA", "image/png")   # a real Blob


def test_fetch_image_all_fail_and_guards(inv_client, monkeypatch):
    monkeypatch.setattr("app.views.inventory_clip.download_image",
                        lambda url, referer=None: {"ok": False, "error": "nope"})
    r = inv_client.post("/api/inventory/inv1/fetch-image", json={"image_url": "https://img.test/a.png"})
    d = r.json()
    assert r.status_code == 200 and d["ok"] is False and d["error"] == "nope" and d["attached"] == 0
    doc = inventory.get("inv1")
    assert not doc.get("_images")
    r = inv_client.post("/api/inventory/inv1/fetch-image", json={"image_urls": ["ftp://x"]})
    assert r.status_code == 400
    r = inv_client.post("/api/inventory/nope/fetch-image", json={"image_url": "https://img.test/a.png"})
    assert r.status_code == 404


def test_board_update_drops_clip_only_keys(inv_client):
    r = inv_client.post("/api/inventory/inv1", json={"Brand": "Makita", "image_url": "x", "images": []})
    assert r.json()["ok"]
    doc = inventory.get("inv1")
    assert doc["Brand"] == "Makita" and "image_url" not in doc and "images" not in doc


def test_routes_registered():
    from app.urls import VIEW_MODULES
    from app.views import inventory, inventory_clip
    from tests.dbhelper import routes
    mods = list(VIEW_MODULES)
    assert mods.index(inventory_clip) < mods.index(inventory)      # /api/inventory/items before /<doc_id>
    paths = set(routes(inventory_clip))
    assert "/api/inventory/items" in paths
    assert "/api/inventory/clip/prepare" in paths
    assert "/api/inventory/<str:doc_id>/fetch-image" in paths
    assert "/inventory/clip" in paths
