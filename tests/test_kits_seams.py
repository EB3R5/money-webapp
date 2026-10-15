import pytest
"""The card-collection seams Kits ride on (ADR-0018, plan slice 2): `kits_enabled` ships each
row's Kits as `_kits` and composes the delete cascade; the modal is a shared partial; a
collection may render a page of its own (`template` + `page_context`) over the same routes."""


from app.views.inventory import _inventory
from app.store.documents import documents as documents_store
from app.store.kit_members import kit_members
from app.store.kits import kits
from tests import dbhelper


@pytest.fixture
def seams_client(store_client):
    """Inventory seeded; inv1 is in two Kits and carries one Document, inv2 in none."""
    dbhelper.seed_inventory()
    kits.insert({"_id": "k1", "Name": "Home gym"})
    kits.insert({"_id": "k2", "Name": "Backups"})
    kit_members.add("k1", ["inventory:inv1"])
    kit_members.add("k2", ["inventory:inv1"])
    documents_store.insert({"_id": "d1", "parent_table": "inventory", "parent_id": "inv1",
                                  "name": "manual.md", "kind": "md", "content_type": "text/markdown",
                                  "size": 2, "body": "# m"})
    return store_client


# --- kits_enabled off: nothing changes ---------------------------------------------------

def test_flag_off_ships_no_kits_and_leaves_memberships_on_delete(seams_client, monkeypatch):
    monkeypatch.setattr(_inventory, "kits_enabled", False)   # the boards turn it on (slice 4)
    html = (seams_client.get("/inventory")).text
    assert "kitsEnabled: false" in html
    assert '"_kits"' not in html
    r = seams_client.post("/api/inventory/delete", json={"ids": ["inv1"]})
    assert r.json() == {"ok": True, "deleted": 1}
    assert kit_members.count({"member_id": "inv1"}) == 2       # untouched
    assert documents_store.count({"parent_id": "inv1"}) == 0   # the documents cascade still runs


# --- kits_enabled on ------------------------------------------------------------------------

def test_flag_on_ships_kits_by_name_per_row(seams_client, monkeypatch):
    monkeypatch.setattr(_inventory, "kits_enabled", True)
    html = (seams_client.get("/inventory")).text
    assert "kitsEnabled: true" in html
    assert '"_kits": [{"id": "k2", "name": "Backups"}, {"id": "k1", "name": "Home gym"}]' in html
    assert '"_kits": []' in html                                    # inv2: present, empty


def test_flag_on_delete_cascades_memberships_and_documents(seams_client, monkeypatch):
    monkeypatch.setattr(_inventory, "kits_enabled", True)
    r = seams_client.post("/api/inventory/delete", json={"ids": ["inv1"]})
    assert r.json() == {"ok": True, "deleted": 1}
    assert kit_members.count({"member_id": "inv1"}) == 0
    assert documents_store.count({"parent_id": "inv1"}) == 0
    assert kits.count() == 2                                  # the Kits themselves stay


def test_a_given_delete_hook_replaces_the_default_cascade(seams_client, monkeypatch):
    seen = []

    def hook(ids):
        seen.append(list(ids))

    monkeypatch.setattr(_inventory, "kits_enabled", True)
    monkeypatch.setattr(_inventory, "delete_hook", hook)
    seams_client.post("/api/inventory/delete", json={"ids": ["inv1"]})
    assert seen == [["inv1"]]
    assert kit_members.count({"member_id": "inv1"}) == 2       # the hook, not the default, ran


# --- the modal partial and the page seam ---------------------------------------------------

def test_boards_render_the_shared_modal_partial(seams_client):
    for slug in ("inventory", "software", "accounts"):
        html = (seams_client.get(f"/{slug}")).text
        assert html.count('id="card-modal"') == 1, slug
        assert 'id="card-form"' in html and 'id="card-close"' in html, slug


def test_template_and_page_context_render_a_page_of_their_own(seams_client, monkeypatch):
    def extra(request, docs, sections):
        assert len(docs) == 2 and sections
        return {"rows": [], "grand": {}}

    monkeypatch.setattr(_inventory, "template", "inventory_overview.html")
    monkeypatch.setattr(_inventory, "page_context", extra)
    r = seams_client.get("/inventory")
    assert r.status_code == 200
    assert "Inventory Overview" in r.text and "No inventory items." in r.text
    assert 'id="card-modal"' not in r.text


# --- slice 4: both boards turn the flag on --------------------------------------------------

def test_both_boards_ship_kits_for_their_rows(store_client):
    from app.views.software import _software
    assert _inventory.kits_enabled is True and _software.kits_enabled is True
    dbhelper.seed_inventory()
    dbhelper.seed_software()
    kits.insert({"_id": "k1", "Name": "Backups"})
    kit_members.add("k1", ["inventory:inv1", "software:s1"])
    for slug in ("inventory", "software"):
        html = (store_client.get(f"/{slug}")).text
        assert "kitsEnabled: true" in html, slug
        assert '"_kits": [{"id": "k1", "name": "Backups"}]' in html, slug
        assert '"_kits": []' in html, slug
