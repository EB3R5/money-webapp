import pytest
"""The Kit page (app/kits.py, routers/kits.py, ADR-0018, plan slice 3) through HTTP: the empty
state, first-by-name, one Kit, 404; the membership route (order, idempotence, unknown keys,
dangling members); the stats rule for inactive software; Name required; the audited delete;
the nav entry and the CSP rule."""


from app import kits as domain
from app.store.deletions import deletions
from app.store.kit_members import kit_members
from app.store.kits import kits
from app.store.software import software
from tests import dbhelper


@pytest.fixture
def kit_client(store_client):
    """Items + Software seeded; two Kits: "Smart home" (empty) and "Backups" (inv1, s1, s3)."""
    dbhelper.seed_inventory()
    dbhelper.seed_software()
    kits.insert({"_id": "k1", "Name": "Smart home"})
    kits.insert({"_id": "k2", "Name": "Backups", "Description": "Paper and disks",
                       "How_To": "1. Scan weekly\n2. `restic forget --prune` monthly"})
    kit_members.add("k2", ["inventory:inv1", "software:s1", "software:s3"])
    return store_client


def _members(client, kit_id, **body):
    return (client.post(f"/api/kits/{kit_id}/members", json=body)).json()


# --- pages --------------------------------------------------------------------------------

def test_empty_state_when_there_are_no_kits(store_client):
    r = store_client.get("/kits")
    assert r.status_code == 200
    assert "No kits yet" in r.text and "New kit" in r.text
    assert 'id="card-modal"' in r.text          # the shared modal is there to create the first one


def test_kits_shows_the_first_by_name_case_insensitive(kit_client):
    kits.insert({"_id": "k0", "Name": "aquarium"})
    html = (kit_client.get("/kits")).text
    assert '<section class="kit" data-kit="k0">' in html
    # sidebar order: aquarium, Backups, Smart home
    assert html.index("aquarium") < html.index(">Backups<") < html.index("Smart home")


def test_one_kit_renders_hero_howto_members_in_order_and_badges(kit_client):
    r = kit_client.get("/kits/k2")
    assert r.status_code == 200
    html = r.text
    assert "Paper and disks" in html
    assert "<li>Scan weekly</li>" in html and "<code>restic forget --prune</code>" in html
    # members in position order: Drill, Obsidian Sync, Old Editor
    i_drill, i_sync, i_old = html.index('data-key="inventory:inv1"'), html.index('data-key="software:s1"'), html.index('data-key="software:s3"')
    assert i_drill < i_sync < i_old
    assert 'href="/inventory/inv1/sheet"' in html
    assert 'href="/software?q=Obsidian%20Sync"' in html
    assert 'class="kit-badge kit-badge-status">uninstalled<' in html   # s3 is not active
    assert 'class="active" data-kit="k2"' in html


def test_stats_count_only_active_software_toward_monthly(kit_client):
    html = (kit_client.get("/kits/k2")).text
    # Drill 2×50 = $100 value; Obsidian Sync $10/mo (using); Old Editor uninstalled → nothing
    assert "3 items · 1 inventory · 2 software\n  · $100 value · $10/mo" in html
    software.update("s1", {"Status": "cancelled"})
    html = (kit_client.get("/kits/k2")).text
    assert "· $100 value</span>" in html and "/mo" not in html.split('id="kit-stats"')[1].split("</span>")[0]


def test_unknown_kit_is_a_404_page(kit_client):
    r = kit_client.get("/kits/nope")
    assert r.status_code == 404 and "No such Kit" in r.text


def test_nav_has_kits_and_the_page_has_no_inline_handlers(kit_client):
    html = (kit_client.get("/kits/k2")).text
    assert '<a href="/kits">Kits</a>' in html
    assert "onclick=" not in html and "onchange=" not in html and "onload=" not in html


# --- membership route -----------------------------------------------------------------------

def test_add_appends_in_order_given_and_is_idempotent(kit_client):
    d = _members(kit_client, "k1", add=["software:s2", "inventory:inv2", "software:s2"])
    assert d["ok"] and d["added"] == ["software:s2", "inventory:inv2"] and d["removed"] == 0
    assert d["member_keys"] == ["software:s2", "inventory:inv2"]
    assert [m["title"] for m in d["members"]] == ["ripgrep", "Pen"]
    d = _members(kit_client, "k1", add=["inventory:inv2", "inventory:inv1"])
    assert d["added"] == ["inventory:inv1"]
    assert d["member_keys"] == ["software:s2", "inventory:inv2", "inventory:inv1"]
    assert d["stats"] == {"count": 3, "n_inv": 2, "n_sw": 1, "value": 110.0, "monthly": 0.0, "with_photo": 0}


def test_unknown_keys_and_rows_are_ignored(kit_client):
    d = _members(kit_client, "k1", add=["inventory:ghost", "accounts:a1", "junk", "", "inventory:inv1"],
                       remove=["software:never"])
    assert d["ok"] and d["added"] == ["inventory:inv1"] and d["removed"] == 0
    assert kit_members.count({"kit_id": "k1"}) == 1
    assert (_members(kit_client, "k1")) ["member_keys"] == ["inventory:inv1"]   # empty body: no change


def test_remove_then_add_in_one_call_and_available_excludes_members(kit_client):
    d = _members(kit_client, "k2", remove=["software:s3", "inventory:inv1"], add=["inventory:inv2"])
    assert d["removed"] == 2 and d["added"] == ["inventory:inv2"]
    assert d["member_keys"] == ["software:s1", "inventory:inv2"]
    avail = {m["key"]: m for m in d["available"]}
    assert set(avail) == {"inventory:inv1", "software:s2", "software:s3"}
    assert avail["inventory:inv1"]["in_kits"] == 0
    assert d["cover"] is None                     # no photos anywhere in the seed


def test_in_kits_hint_counts_other_kits(kit_client):
    _members(kit_client, "k1", add=["inventory:inv1"])          # inv1 now in k1 and k2
    html = (kit_client.get("/kits/k1")).text
    d = _members(kit_client, "k1", remove=["inventory:inv1"])
    assert {m["key"]: m["in_kits"] for m in d["available"]}["inventory:inv1"] == 1   # still in k2
    assert "window.KIT" in html


def test_dangling_member_is_skipped_everywhere(kit_client):
    kit_members.add("k2", ["inventory:vanished"])
    html = (kit_client.get("/kits/k2")).text
    assert "vanished" not in html
    assert "3 items" in html
    assert kit_members.count({"kit_id": "k2"}) == 4   # the row stays; only the view skips it


def test_members_route_404s_for_an_unknown_kit(kit_client):
    r = kit_client.post("/api/kits/nope/members", json={"add": ["inventory:inv1"]})
    assert r.status_code == 404


# --- the Kit's own CRUD through the engine --------------------------------------------------

def test_create_requires_a_name_and_update_cannot_blank_it(kit_client):
    r = kit_client.post("/api/kits/row", json={"Description": "nameless"})
    assert r.status_code == 400 and "name" in r.json()["error"]
    r = kit_client.post("/api/kits/row", json={"Name": "Camping", "How_To": "Pack light"})
    assert r.json()["ok"]
    new_id = r.json()["id"]
    assert (kits.get(new_id))["How_To"] == "Pack light"
    r = kit_client.post(f"/api/kits/{new_id}", json={"Name": "  "})
    assert r.status_code == 400
    r = kit_client.post(f"/api/kits/{new_id}", json={"Name": "Camping trip", "Description": ""})
    assert r.json()["ok"]
    k = kits.get(new_id)
    assert k["Name"] == "Camping trip" and k["Description"] is None


def test_delete_audits_the_kit_and_its_memberships_and_leaves_members(kit_client):
    r = kit_client.post("/api/kits/delete", json={"ids": ["k2"]})
    assert r.json() == {"ok": True, "deleted": 1}
    assert kits.get("k2") is None
    assert kit_members.count({"kit_id": "k2"}) == 0
    logged_kits = deletions.list({"collection": "kits"})
    logged_members = deletions.list({"collection": "kit_members"})
    assert len(logged_kits) == 1 and len(logged_members) == 3
    assert dbhelper.get(dbhelper.inventory, "inv1") is not None   # the Item is untouched
    assert (kit_client.get("/kits")).status_code == 200


# --- domain rules without HTTP --------------------------------------------------------------

def test_cover_prefers_the_kits_own_photo_then_the_first_member_photo():
    members = [{"image": None}, {"image": "/api/inventory/image/m1"}]
    assert domain.cover({"_images": []}, members) == "/api/inventory/image/m1"
    assert domain.cover({"_images": [{"id": "k9"}]}, members) == "/api/kits/image/k9"
    assert domain.cover({}, [{"image": None}]) is None
