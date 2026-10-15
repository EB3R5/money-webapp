import pytest
"""Card-CRUD tests against the shared CardCollection, exercised through the real
HTTP routes — the interface is the test surface. Inventory drives the full
create/update/delete path; accounts drives the read-filter + numeric-coercion path
and proves create/delete stay opt-in. The dirty-diff test is the regression that
locks the wiped-Unit_Cost bug (ADR-0007) in one place for every card page."""


from app.card_collection import CardCollection
from app.views.accounts import _accounts
from app.views.inventory import _inventory
from app.store.blobs import blobs
from app.store.database import database


def store_db_dir():
    return database.data_dir
from app.store.accounts import accounts
from app.store.deletions import deletions
from app.store.inventory import inventory
from tests import dbhelper

COLLECTION = inventory.table

pytestmark = []


@pytest.fixture
def acc_client(store_client):
    """The accounts page on the store, with the four seeded cards."""
    dbhelper.seed_accounts()
    return store_client


@pytest.fixture
def inv_client(store_client):
    """The inventory page on the store, with the two seeded Items (Drill / Pen)."""
    dbhelper.seed_inventory()
    return store_client


# --- the deepening itself: one module, two adapters --------------------------

def test_both_pages_are_the_same_module():
    # Local-substitutable: accounts and inventory are the SAME CardCollection class,
    # not two forks. Delete inventory's CRUD code and it still exists — in the module.
    assert isinstance(_accounts, CardCollection)
    assert isinstance(_inventory, CardCollection)
    assert type(_accounts) is type(_inventory)
    # The dance (serialize/sections/clean/update/create/delete) is defined once.
    for method in ("serialize", "build_sections", "clean", "update", "create", "delete"):
        assert getattr(type(_accounts), method) is getattr(type(_inventory), method)


# --- inventory: full CRUD ----------------------------------------------------

def test_inventory_page_renders_cards_and_grand(inv_client):
    r = inv_client.get("/inventory")
    assert r.status_code == 200
    body = r.text
    assert "Drill" in body and "Pen" in body
    assert "$110" in body  # grand total: 2×50 + 10×1


def test_create_item_auto_ids_and_qty_default(inv_client):
    r = inv_client.post("/api/inventory/row", json={"Item_Name": "Hammer", "Category": "Tools"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] and data["Item_ID"].startswith("MAN-")
    doc = inventory.get(data["id"])
    assert doc["Item_Name"] == "Hammer"
    assert doc["Qty"] == 1.0            # default applied, typed by the store
    assert doc["_created_at"]


def test_dirty_diff_update_does_not_wipe_untouched_fields(inv_client):
    # The whole point of ADR-0007: send only the changed field; Unit_Cost survives.
    r = inv_client.post("/api/inventory/inv1", json={"Item_Name": "Cordless Drill"})
    assert r.status_code == 200 and r.json() == {"ok": True, "matched": 1}
    doc = inventory.get("inv1")
    assert doc["Item_Name"] == "Cordless Drill"
    assert doc["Unit_Cost"] == 50.0    # NOT wiped
    assert doc["Qty"] == 2.0
    assert doc["_edited_at"]


def test_inventory_typed_values_round_trip_plain(inv_client):
    inv_client.post("/api/inventory/inv2", json={"Unit_Cost": " 2 "})
    doc = inventory.get("inv2")
    assert doc["Unit_Cost"] == 2.0     # the store types the REAL column
    page = (inv_client.get("/inventory")).text
    assert "×10" in page and "×10.0" not in page   # and the page shows what was typed


def test_delete_audits_then_removes(inv_client):
    r = inv_client.post("/api/inventory/delete", json={"ids": ["inv1"]})
    assert r.status_code == 200 and r.json() == {"ok": True, "deleted": 1}
    assert inventory.get("inv1") is None
    logged = deletions.one({"collection": COLLECTION})
    assert logged is not None and logged["doc"]["_id"] == "inv1"


def test_update_missing_id_matches_nothing(inv_client):
    r = inv_client.post("/api/inventory/nope", json={"Item_Name": "Ghost"})
    assert r.json() == {"ok": False, "matched": 0}


def test_update_whitelist_rejects_unknown_fields(inv_client):
    inv_client.post("/api/inventory/inv2", json={"Junk": "x", "Item_Name": "Marker"})
    doc = inventory.get("inv2")
    assert "Junk" not in doc and doc["Item_Name"] == "Marker"


# --- accounts: read filter, numeric coercion, opt-out of create/delete -------

def test_accounts_active_filter_skips_closed_and_nameless(acc_client):
    r = acc_client.get("/accounts?status=active")
    assert r.status_code == 200
    body = r.text
    assert "Checking" in body and "Visa" in body
    assert "Old Card" not in body          # Closed hidden
    # nameless placeholder (acc4) carries no Account text, so nothing to leak


def test_accounts_closed_filter_shows_only_closed(acc_client):
    body = (acc_client.get("/accounts?status=closed")).text
    assert "Old Card" in body and "Checking" not in body


def test_account_update_coerces_numbers_and_nulls_blanks(acc_client):
    r = acc_client.post("/api/accounts/acc1",
                          json={"Amount": "1,234.56", "Category": "  ", "Status": "Updated"})
    assert r.json() == {"ok": True, "matched": 1}
    doc = accounts.get("acc1")
    assert doc["Amount"] == 1234.56        # coerced to float
    assert doc["Category"] is None         # blank text → null
    assert doc["Status"] == "Updated"


def test_account_update_bad_number_is_400(acc_client):
    r = acc_client.post("/api/accounts/acc1", json={"Amount": "abc"})
    assert r.status_code == 400
    assert "not a number" in r.json()["error"]


def test_inventory_image_routes_registered():
    from app.views import accounts as acc_views, inventory as inv_views
    paths = set(dbhelper.routes(inv_views))
    assert "/api/inventory/image/<str:file_id>" in paths
    assert "/api/inventory/<str:doc_id>/images" in paths
    assert "/api/inventory/<str:doc_id>/images/delete" in paths
    # accounts opted out of images entirely.
    assert not any("image" in p for p in dbhelper.routes(acc_views))


def test_inventory_serialize_includes_images(inv_client):
    inventory.update("inv1", {"_images": [{"id": "f1", "filename": "drill.png"}]})
    body = (inv_client.get("/inventory")).text
    assert "/api/inventory/image/f1" in body          # thumbnail wired into the card


def test_image_upload_serve_and_delete_round_trip(inv_client):
    r = inv_client.post("/api/inventory/inv1/images",
                              files=[("files", ("drill.png", b"\x89PNG-bytes", "image/png"))])
    body = r.json()
    assert body["ok"] and len(body["images"]) == 1
    entry = body["images"][0]
    assert entry["content_type"] == "image/png" and entry["filename"] == "drill.png"
    assert blobs.get(entry["id"], kind="photo") == (b"\x89PNG-bytes", "image/png")
    assert not (store_db_dir() / "photos").exists(), "no files beside the database"
    # served by photo id alone
    r = inv_client.get(f"/api/inventory/image/{entry['id']}")
    assert r.status_code == 200 and r.content == b"\x89PNG-bytes"
    assert r.headers["content-type"].startswith("image/png")
    assert (inv_client.get("/api/inventory/image/nope")).status_code == 404
    # delete unlinks the entry and removes the Blob
    r = inv_client.post("/api/inventory/inv1/images/delete", json={"id": entry["id"]})
    assert r.json() == {"ok": True}
    assert (inventory.get("inv1"))["_images"] == []
    assert blobs.get(entry["id"]) is None


def test_image_route_serves_only_photo_blobs(inv_client):
    blobs.put("doc_bytes", "document", b"%PDF", "application/pdf")
    assert (inv_client.get("/api/inventory/image/doc_bytes")).status_code == 404


def test_row_delete_keeps_photo_blobs(inv_client):
    r = inv_client.post("/api/inventory/inv1/images",
                              files=[("files", ("drill.png", b"\x89PNG-bytes", "image/png"))])
    entry = r.json()["images"][0]
    r = inv_client.post("/api/inventory/delete", json={"ids": ["inv1"]})
    assert r.json()["deleted"] == 1
    assert inventory.get("inv1") is None
    assert blobs.get(entry["id"]) == (b"\x89PNG-bytes", "image/png"), "ADR-0005 addendum: a restore finds its bytes"


def test_image_delete_unlinks_from_doc(inv_client):
    inventory.update("inv1", {"_images": [{"id": "a"}, {"id": "b"}]})
    r = inv_client.post("/api/inventory/inv1/images/delete", json={"id": "a"})
    assert r.json() == {"ok": True}
    doc = inventory.get("inv1")
    assert [im["id"] for im in doc["_images"]] == ["b"]


def test_create_delete_routes_registered():
    # Both adapters opt in to /row + /delete (accounts since the accounts-CRUD change).
    acc_paths = set(dbhelper.routes(_accounts.urlpatterns()))
    inv_paths = set(dbhelper.routes(_inventory.urlpatterns()))
    assert "/api/inventory/row" in inv_paths and "/api/inventory/delete" in inv_paths
    assert "/api/accounts/row" in acc_paths and "/api/accounts/delete" in acc_paths


def test_account_create_mints_id_and_defaults_active(acc_client):
    r = acc_client.post("/api/accounts/row",
                          json={"Account Kind": "Bank/cash", "Account": "New Brokerage",
                                "Amount": "2,500"})
    body = r.json()
    assert body["ok"]
    doc = accounts.get(body["id"])
    assert doc["Account ID"].startswith("MAN-") and len(doc["Account ID"]) == 12
    assert doc["Status"] == "Active"              # visible under the default filter
    assert doc["Amount"] == 2500.0                # numeric coercion applies on create
    # the type preset stamps classification — never typed on this form
    assert doc["Type"] == "Assets" and doc["Group"] == "Current Assets"
    assert doc["Account Type"] == "Checking Account"
    assert (acc_client.get("/accounts?status=active")).text.count("New Brokerage")


def test_account_create_requires_type(acc_client):
    r = acc_client.post("/api/accounts/row", json={"Account": "No Kind"})
    assert r.status_code == 400 and "type" in r.json()["error"]


def test_account_type_select_renders(acc_client):
    body = (acc_client.get("/accounts")).text
    assert '<select name="Account Kind">' in body
    for kind in ("Bank/cash", "Credit card", "Common stock", "Loan"):
        assert kind in body


def test_account_delete_audits_then_removes(acc_client):
    r = acc_client.post("/api/accounts/delete", json={"ids": ["acc1"]})
    assert r.json() == {"ok": True, "deleted": 1}
    assert accounts.get("acc1") is None
    snap = deletions.one({"collection": "accounts"})
    assert snap and snap["doc"]["_id"] == "acc1"


def test_accounts_hidden_rows_never_render(acc_client):
    # an unlinked feed account arrives hidden (the SimpleFIN slices) — no card, any filter
    dbhelper.seed(accounts, [{"_id": "sfa_x", "Account ID": "sf-1", "Account": "Ghost Bank",
                                    "Status": "Unlinked", "is_hidden": True, "Amount": 5.0}])
    for status in ("active", "closed", "all"):
        html = (acc_client.get(f"/accounts?status={status}")).text
        assert 'data-id="sfa_x"' not in html                    # no card under any filter
        assert 'data-feed-id="sfa_x"' in html                   # only the unlinked strip names it


# --- search box (instant client-side filter; the JS is checked in the browser) --------

def test_inventory_page_renders_search_box_and_fields(inv_client):
    body = (inv_client.get("/inventory")).text
    assert 'id="card-search"' in body and 'id="card-no-match"' in body
    assert 'id="card-count">2<' in body and 'id="card-grand">$110<' in body
    assert 'class="muted acct-section-total"' in body
    fields = body.split("searchFields: ", 1)[1].split("]", 1)[0]
    assert '"Item_ID"' in fields and '"Notes"' in fields and '"Brand"' in fields
    assert '"Link"' not in fields and '"Qty"' not in fields


def test_inventory_page_prefills_the_search_term(inv_client):
    body = (inv_client.get("/inventory?q=drill")).text
    assert 'value="drill"' in body
    body = (inv_client.get('/inventory?q="<x>')).text
    assert 'value="&#34;&lt;x&gt;"' in body                     # autoescaped


def test_accounts_page_has_no_search_box(acc_client):
    body = (acc_client.get("/accounts")).text
    assert 'id="card-search"' not in body and "searchFields: []" in body


# --- transplanted engine options: group toggle, entry sort, link icon, default status ------

def test_build_sections_takes_an_alternate_field_order_and_entry_sort():
    docs = [{"_id": "a", "_amount": 1.0, "Category": "X", "Kind": "cli", "Item_Name": "b"},
            {"_id": "b", "_amount": 5.0, "Category": "Y", "Kind": "cli", "Item_Name": "a"},
            {"_id": "c", "_amount": 2.0, "Category": "X", "Kind": "app", "Item_Name": "c"}]
    by_cat = _inventory.build_sections([dict(d) for d in docs])
    assert [s["label"] for s in by_cat] == ["Y", "X"]                       # by total desc
    by_kind = _inventory.build_sections([dict(d) for d in docs], "Kind", ["app", "cli"])
    assert [s["label"] for s in by_kind] == ["app", "cli"]                  # the given order
    assert [e["_id"] for e in by_kind[1]["entries"]] == ["b", "a"]          # amount desc within
    cfg = CardCollection(slug="t", store=inventory, id_field="Item_ID", title_field="Item_Name",
                         group_by="Category", fields=[], amount=lambda d: d.get("_amount"),
                         heading="T", noun="t", entry_sort=lambda d: d["Item_Name"])
    assert [e["_id"] for e in cfg.build_sections([dict(d) for d in docs], "Kind", None)[0]["entries"]] == ["b", "a"]


def test_cards_are_div_buttons_and_pages_without_options_render_no_toggle_or_link(inv_client, acc_client):
    for path in ("/inventory", "/inventory?group=kind"):
        body = (inv_client.get(path)).text
        assert '<div role="button" tabindex="0" class="acct-card' in body
        assert "group-toggle" not in body and "acct-link" not in body
    body = (acc_client.get("/accounts")).text
    assert "group-toggle" not in body and "acct-link" not in body
    assert 'class="status-filter"' in body and "onchange" not in body     # handler lives in card-editor.js
