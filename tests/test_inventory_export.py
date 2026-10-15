"""Inventory Item export — the pure bundle builder (app/inventory_export.py), the
export-fields rule beside the Item schema (app/inventory_item.py), and the HTTP surface
(routers/inventory_export.py): the Item sheet page and the zip export over real photo
files beside the test's data directory."""

import io
import zipfile
from datetime import UTC, datetime

import pytest

from app.inventory_export import (MD_NAME, PNG_NAME, bundle, folder_name, markdown,
                                  photo_ext, photo_paths, sheet_context)

from app.inventory_item import FIELD_NAMES, SHEET_HIDDEN, export_fields
from app.store.blobs import blobs
from app.store.inventory import inventory
from tests import dbhelper


@pytest.fixture
def inv_client(store_client):
    dbhelper.seed_inventory()
    return store_client

DOC = {"_id": "man_0123456789a3f9", "Item_ID": "MAN-1", "Item_Name": "Dyson V11",
       "Category": "Appliances", "Brand": "Dyson", "Model": "V11 Absolute", "Qty": "1",
       "Unit_Cost": "599", "Salvage_Value": "50", "Useful_Life_Years": "5",
       "Classification": "Fixed", "Link": "https://shop.test/v11", "Notes": "Bought new.",
       "_src": "manual", "_images": [{"id": "f1", "filename": "a.jpg", "content_type": "image/jpeg"},
                                     {"id": "f2", "filename": "b", "content_type": "image/png"}]}
PHOTOS = [(b"JPG", "image/jpeg", "a.jpg"), (b"PNG", "image/png", "b")]


# --- export_fields (the one statement of what an export carries) ------------------------

def test_export_fields_declared_order_plus_value_no_internals():
    f = export_fields(DOC)
    assert list(f) == FIELD_NAMES + ["Value"]
    assert f["Value"] == 599.0
    assert f["Color"] == ""                       # blank, not None
    assert not any(k.startswith("_") for k in f)  # _id / _images / _src never leak


# --- naming ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, expect", [
    ("Dyson V11", "Dyson V11 (a3f9)"),
    ('Bad: "name"/with\\slashes?', "Bad name with slashes (a3f9)"),
    ("   ", "item (a3f9)"),
    ("Été à Paris", "Été à Paris (a3f9)"),
])
def test_folder_name(name, expect):
    assert folder_name({**DOC, "Item_Name": name}) == expect


def test_folder_name_truncates_long_names():
    assert len(folder_name({**DOC, "Item_Name": "x" * 300})) <= 80 + len(" (a3f9)")


@pytest.mark.parametrize("ct, fn, ext", [
    ("image/jpeg", None, "jpg"), ("image/png; charset=binary", "x", "png"),
    ("image/webp", "a.jpg", "webp"), ("application/octet-stream", "IMG_1.HEIC", "heic"),
    (None, "noext", "bin"), ("", None, "bin"),
])
def test_photo_ext(ct, fn, ext):
    assert photo_ext(ct, fn) == ext


def test_photo_paths_numbered_in_order():
    assert photo_paths(PHOTOS) == ["photos/01.jpg", "photos/02.png"]


# --- markdown -------------------------------------------------------------------------

def test_markdown_front_matter_and_body():
    md = markdown(DOC, ["photos/01.jpg", "photos/02.png"], datetime(2026, 9, 4, tzinfo=UTC))
    head, body = md.split("---\n", 2)[1:]
    for name in FIELD_NAMES:                       # every declared field, raw names
        assert f"\n{name}: " in "\n" + head
    assert 'Item_Name: "Dyson V11"' in head
    assert "Value: 599.0" in head
    assert 'exported_at: "2026-09-04T00:00:00+00:00"' in head
    assert "# Dyson V11" in body
    assert "![Dyson V11](photos/01.jpg)" in body      # hero = first photo, relative link
    assert "![photo 2](photos/02.png)" in body
    assert "| Value | $599.00 |" in body
    assert "| Link | [https://shop.test/v11](https://shop.test/v11) |" in body
    assert "| Color |" not in body                    # blanks hidden
    for hidden in SHEET_HIDDEN:                       # accounting fields: data yes, sheet no
        assert f"| {hidden.replace('_', ' ')} |" not in body
        assert f"\n{hidden}: " in "\n" + head
    assert "## Notes\n\nBought new." in body
    assert f"![sheet]({PNG_NAME})" in body


def test_markdown_without_photos_or_png():
    md = markdown({**DOC, "Notes": ""}, [], png_name=None)
    assert "![" not in md and "## Photos" not in md and "## Notes" not in md and "## Sheet" not in md


# --- sheet_context --------------------------------------------------------------------

def test_sheet_context_hero_thumbs_rows():
    ctx = sheet_context(DOC, ["/img/1", "/img/2", "/img/3"])
    assert ctx["hero"] == "/img/1" and ctx["thumbs"] == ["/img/2", "/img/3"]
    labels = [r[0] for r in ctx["rows"]]
    assert "Category" in labels and "Link" in labels
    assert "Item Name" not in labels and "Brand" not in labels   # headline, not spec
    assert "Color" not in labels                                  # blank hidden
    assert "Classification" not in labels                         # accounting-only
    assert ctx["title"] == "Dyson V11" and ctx["value"] == 599.0
    assert sheet_context(DOC, [])["hero"] is None


# --- bundle ---------------------------------------------------------------------------

def _entries(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


def test_bundle_layout_with_png():
    name, data = bundle(DOC, PHOTOS, b"PNGBYTES")
    assert name == "Dyson V11 (a3f9).zip"
    e = _entries(data)
    assert set(e) == {f"Dyson V11 (a3f9)/{MD_NAME}", f"Dyson V11 (a3f9)/{PNG_NAME}",
                      "Dyson V11 (a3f9)/photos/", "Dyson V11 (a3f9)/photos/01.jpg",
                      "Dyson V11 (a3f9)/photos/02.png"}
    assert e["Dyson V11 (a3f9)/photos/01.jpg"] == b"JPG"       # originals, untouched
    assert e[f"Dyson V11 (a3f9)/{PNG_NAME}"] == b"PNGBYTES"
    assert b"![Dyson V11](photos/01.jpg)" in e[f"Dyson V11 (a3f9)/{MD_NAME}"]


def test_bundle_no_photos_no_png_still_exports():
    name, data = bundle({**DOC, "_images": []}, [], None)
    e = _entries(data)
    assert set(e) == {f"Dyson V11 (a3f9)/{MD_NAME}", "Dyson V11 (a3f9)/photos/"}
    assert b"card.png" not in e[f"Dyson V11 (a3f9)/{MD_NAME}"]


# --- HTTP -----------------------------------------------------------------------------

def test_sheet_page_renders(inv_client):
    inventory.update("inv1", {"_images": [{"id": "f1", "content_type": "image/png"}], "Notes": "hello"})
    r = inv_client.get("/inventory/inv1/sheet")
    assert r.status_code == 200
    body = r.text
    assert "Drill" in body and "Bosch" in body and "$100.00" in body
    assert 'src="/api/inventory/image/f1"' in body       # hero from the first photo
    assert 'id="sheet-export"' in body and "inventory-sheet.js" in body
    assert "hello" in body


def test_sheet_page_404(inv_client):
    assert (inv_client.get("/inventory/nope/sheet")).status_code == 404


def test_export_zip_skips_missing_photo_and_includes_png(inv_client):
    ok = blobs.new_photo(b"JPGDATA", "image/jpeg", "a.jpg")          # a real Blob
    gone = {"id": "b" * 32, "filename": "b.jpg", "content_type": "image/jpeg"}   # no Blob behind it
    inventory.update("inv1", {"_images": [ok, gone]})

    r = inv_client.post("/api/inventory/inv1/export",
                          files={"png": ("card.png", b"PNG!", "image/png")})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="Drill (inv1).zip"' in r.headers["content-disposition"]
    e = _entries(r.content)
    assert set(e) == {"Drill (inv1)/item.md", "Drill (inv1)/card.png",
                      "Drill (inv1)/photos/", "Drill (inv1)/photos/01.jpg"}   # "gone" skipped
    assert e["Drill (inv1)/card.png"] == b"PNG!"
    assert b"exported_at:" in e["Drill (inv1)/item.md"]


def test_export_without_png(inv_client):
    r = inv_client.post("/api/inventory/inv2/export")
    assert r.status_code == 200
    assert set(_entries(r.content)) == {"Pen (inv2)/item.md", "Pen (inv2)/photos/"}


def test_export_404(inv_client):
    assert (inv_client.post("/api/inventory/nope/export")).status_code == 404


def test_columns_tree_carries_doc_id_for_sheet_link(inv_client):
    d = (inv_client.get("/api/inventory/tree")).json()
    items = [i for g in d["groups"] for c in g["categories"] for s in c["subcategories"]
             for i in s["items"]]
    assert {i["doc_id"] for i in items} == {"inv1", "inv2"}


def test_card_page_has_open_sheet_action(inv_client):
    body = (inv_client.get("/inventory")).text
    assert 'id="card-sheet"' in body
    assert 'id="card-sheet"' not in (inv_client.get("/accounts")).text


@pytest.mark.parametrize("doc_id, expect", [
    ("man_0123456789a3f9", "a3f9"), ("raw__inventory_foundation__inventory__r35", "r35"),
    ("inv1", "inv1"), ("", ""),
])
def test_short_id(doc_id, expect):
    from app.inventory_export import short_id
    assert short_id(doc_id) == expect


# --- Kits on the sheet and in the bundle (ADR-0018, plan slice 4) ------------------------

KITS = [{"id": "k2", "name": "Backups"}, {"id": "k1", "name": "Home gym"}]


def test_sheet_context_carries_kits_or_an_empty_list():
    assert sheet_context(DOC, [], KITS)["kits"] == KITS
    assert sheet_context(DOC, [])["kits"] == []


def test_markdown_front_matter_lists_kit_names_or_omits_the_key():
    md = markdown(DOC, [], datetime(2026, 9, 4, tzinfo=UTC), kits=KITS)
    head = md.split("---\n", 2)[1]
    assert '\nkits:\n  - "Backups"\n  - "Home gym"\nexported_at:' in head
    assert "kits" not in markdown(DOC, [], datetime(2026, 9, 4, tzinfo=UTC)).split("---\n", 2)[1]


def test_bundle_passes_kits_into_the_front_matter():
    _name, data = bundle(DOC, [], None, datetime(2026, 9, 4, tzinfo=UTC), kits=KITS)
    md = next(v for k, v in _entries(data).items() if k.endswith(MD_NAME)).decode()
    assert '  - "Home gym"' in md


@pytest.fixture
def kitted_client(inv_client):
    from app.store.kit_members import kit_members
    from app.store.kits import kits
    kits.insert({"_id": "k1", "Name": "Home gym"})
    kits.insert({"_id": "k2", "Name": "Backups"})
    kit_members.add("k1", ["inventory:inv1"])
    kit_members.add("k2", ["inventory:inv1"])
    return inv_client


def test_sheet_page_shows_the_kits_row_only_when_in_a_kit(kitted_client):
    html = (kitted_client.get("/inventory/inv1/sheet")).text
    assert "<dt>Kits</dt>" in html
    assert '<a href="/kits/k2">Backups</a> · <a href="/kits/k1">Home gym</a>' in html
    html = (kitted_client.get("/inventory/inv2/sheet")).text
    assert "<dt>Kits</dt>" not in html


def test_export_front_matter_lists_the_items_kits(kitted_client):
    r = kitted_client.post("/api/inventory/inv1/export")
    md = next(v for k, v in _entries(r.content).items() if k.endswith(MD_NAME)).decode()
    assert 'kits:\n  - "Backups"\n  - "Home gym"\n' in md
    r = kitted_client.post("/api/inventory/inv2/export")
    md = next(v for k, v in _entries(r.content).items() if k.endswith(MD_NAME)).decode()
    assert "kits:" not in md
