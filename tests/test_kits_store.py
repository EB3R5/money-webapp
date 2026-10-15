"""Kits groundwork (ADR-0018): migration 0012 applies, the kits / kit_members stores, the
member-key rule, uniqueness per (kit, member), the kit-side cascade, and the one-query
`list_for_members` shape the card pages attach as `_kits`."""

import pytest

from app.store.database import database
from app.store.kit_members import kit_members, member_key, split_key
from app.store.kits import kits
from tests import dbhelper


@pytest.fixture
def kit_db(store_db):
    """Two Items, three Software rows, one empty Kit."""
    dbhelper.seed_inventory()
    dbhelper.seed_software()
    kits.insert({"_id": "k1", "Name": "Home gym", "Description": "The spare room"})
    return store_db


# --- the member key -------------------------------------------------------------------

def test_member_key_round_trip():
    assert member_key("inventory", "abc") == "inventory:abc"
    assert split_key("inventory:abc") == ("inventory", "abc")
    assert split_key("software:x:y") == ("software", "x:y")


@pytest.mark.parametrize("bad", ["", "abc", "accounts:abc", "inventory:", None, 7])
def test_member_key_rejects_malformed_and_unknown_tables(bad):
    assert split_key(bad) is None


# --- schema -----------------------------------------------------------------------------

def test_migration_0012_applied(kit_db):
    db = database
    with db.acquire() as conn:
        cur = conn.execute("SELECT MAX(version) FROM schema_version")
        assert (cur.fetchone())[0] >= 12
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('kits', 'kit_members')")
        assert sorted(r[0] for r in cur.fetchall()) == ["kit_members", "kits"]


def test_kit_rows_round_trip_through_the_store(kit_db):
    k = kits.get("k1")
    assert k["Name"] == "Home gym" and k["Description"] == "The spare room"
    assert k["How_To"] is None and k["_images"] is None
    kits.update("k1", {"How_To": "1. Warm up", "_images": [{"id": "a1b2", "filename": "gym.jpg"}]})
    k = kits.get("k1")
    assert k["How_To"] == "1. Warm up"


# --- membership -------------------------------------------------------------------------

def test_add_appends_in_order_and_skips_repeats(kit_db):
    added = kit_members.add("k1", ["inventory:inv2", "software:sw1", "inventory:inv2"])
    assert added == ["inventory:inv2", "software:sw1"]
    # a second call: the repeat is ignored, the new one lands after
    assert kit_members.add("k1", ["inventory:inv2", "inventory:inv1"]) == ["inventory:inv1"]
    rows = kit_members.list_for_kit("k1")
    assert [r["key"] for r in rows] == ["inventory:inv2", "software:sw1", "inventory:inv1"]
    assert [r["position"] for r in rows] == [1, 2, 3]


def test_add_ignores_malformed_keys_and_unknown_tables(kit_db):
    assert kit_members.add("k1", ["accounts:a1", "junk", "", "software:sw2"]) == ["software:sw2"]
    assert kit_members.add("k1", []) == []
    assert kit_members.add("k1", None) == []


def test_unique_per_kit_and_member_is_enforced_by_the_index(kit_db):
    kit_members.add("k1", ["inventory:inv1"])
    with pytest.raises(Exception):   # sqlite3.IntegrityError — the index is the last line
        kit_members.insert({"kit_id": "k1", "member_table": "inventory", "member_id": "inv1",
                                  "position": 99})
    assert kit_members.count({"kit_id": "k1"}) == 1


def test_a_member_may_belong_to_several_kits(kit_db):
    kits.insert({"_id": "k2", "Name": "Smart home"})
    kit_members.add("k1", ["inventory:inv1"])
    kit_members.add("k2", ["inventory:inv1"])
    assert kit_members.count({"member_id": "inv1"}) == 2


def test_remove_drops_only_the_named_members(kit_db):
    kit_members.add("k1", ["inventory:inv1", "inventory:inv2", "software:sw1"])
    assert kit_members.remove("k1", ["inventory:inv2", "software:nope", "junk"]) == 1
    assert [r["key"] for r in kit_members.list_for_kit("k1")] == ["inventory:inv1", "software:sw1"]
    # positions are not renumbered: order added survives a removal
    assert [r["position"] for r in kit_members.list_for_kit("k1")] == [1, 3]
    # and the next add still lands after the highest position
    kit_members.add("k1", ["software:sw2"])
    assert [r["position"] for r in kit_members.list_for_kit("k1")] == [1, 3, 4]


def test_deleting_a_kit_cascades_its_memberships(kit_db):
    kit_members.add("k1", ["inventory:inv1", "software:sw1"])
    assert kit_members.count() == 2
    kits.delete("k1")
    assert kit_members.count() == 0


def test_delete_for_members_is_the_item_side_cascade(kit_db):
    kits.insert({"_id": "k2", "Name": "Smart home"})
    kit_members.add("k1", ["inventory:inv1", "inventory:inv2"])
    kit_members.add("k2", ["inventory:inv1", "software:sw1"])
    assert kit_members.delete_for_members("inventory", ["inv1"]) == 2
    assert [r["key"] for r in kit_members.list_for_kit("k1")] == ["inventory:inv2"]
    assert [r["key"] for r in kit_members.list_for_kit("k2")] == ["software:sw1"]
    assert kit_members.delete_for_members("inventory", []) == 0
    assert kit_members.delete_for_members("accounts", ["x"]) == 0


def test_list_for_members_groups_kits_by_member_key_by_name(kit_db):
    kits.insert({"_id": "k2", "Name": "Backups"})
    kits.insert({"_id": "k3", "Name": "smart home"})
    kit_members.add("k1", ["inventory:inv1", "software:sw1"])
    kit_members.add("k2", ["inventory:inv1"])
    kit_members.add("k3", ["inventory:inv1"])
    got = kit_members.list_for_members("inventory", ["inv1", "inv2", "ghost"])
    assert list(got) == ["inventory:inv1"]
    assert [k["name"] for k in got["inventory:inv1"]] == ["Backups", "Home gym", "smart home"]
    assert got["inventory:inv1"][0] == {"id": "k2", "name": "Backups"}
    assert kit_members.list_for_members("software", ["sw1"]) == {
        "software:sw1": [{"id": "k1", "name": "Home gym"}]}
    assert kit_members.list_for_members("inventory", []) == {}
    assert kit_members.list_for_members("accounts", ["a1"]) == {}
