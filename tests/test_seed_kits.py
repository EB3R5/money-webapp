"""scripts/seed_kits.py (ADR-0018, plan D11): business ids → row ids, idempotent by Kit
name, text never overwritten, unknown ids reported and not fatal, dry run writes nothing."""

import pytest

from app.store.kit_members import kit_members
from app.store.kits import kits
from scripts.seed_kits import load, seed
from tests import dbhelper

ROWS = [
    {"name": "Backups", "description": "Paper and disks", "how_to": "1. Scan weekly",
     "members": ["inventory:X1", "software:SW-001", "software:SW-404"]},
    {"name": "Office", "members": ["inventory:X2"]},
]


@pytest.fixture
def seeded(store_db):
    dbhelper.seed_inventory()      # X1 Drill (inv1), X2 Pen (inv2)
    dbhelper.seed_software()       # SW-001 (s1), SW-002 (s2), SW-003 (s3)
    return store_db


def test_first_run_creates_kits_and_resolves_business_ids(seeded):
    report = seed(ROWS)
    assert report["created"] == ["Backups", "Office"] and report["existing"] == []
    assert report["added"] == {"Backups": ["inventory:inv1", "software:s1"], "Office": ["inventory:inv2"]}
    assert report["unknown"] == {"Backups": ["software:SW-404"]}
    backups = kits.one({"Name": "Backups"})
    assert backups["Description"] == "Paper and disks" and backups["How_To"] == "1. Scan weekly"
    assert [r["key"] for r in kit_members.list_for_kit(backups["_id"])] == ["inventory:inv1", "software:s1"]


def test_second_run_changes_nothing(seeded):
    seed(ROWS)
    before = (kits.count(), kit_members.count())
    report = seed(ROWS)
    assert report["created"] == [] and report["existing"] == ["Backups", "Office"]
    assert report["added"] == {"Backups": [], "Office": []}
    assert (kits.count(), kit_members.count()) == before


def test_existing_kit_keeps_its_text_and_gains_only_missing_members(seeded):
    kit_id = kits.insert({"Name": "backups", "Description": "My own words", "How_To": "Mine"})
    kit_members.add(kit_id, ["software:s1"])
    report = seed(ROWS)
    assert report["existing"] == ["Backups"]                     # matched case-insensitively
    assert report["added"]["Backups"] == ["inventory:inv1"]
    k = kits.get(kit_id)
    assert k["Description"] == "My own words" and k["How_To"] == "Mine" and k["Name"] == "backups"
    assert [r["key"] for r in kit_members.list_for_kit(kit_id)] == ["software:s1", "inventory:inv1"]


def test_dry_run_reports_and_writes_nothing(seeded):
    report = seed(ROWS, dry_run=True)
    assert report["created"] == ["Backups", "Office"]
    assert report["added"]["Backups"] == ["inventory:inv1", "software:s1"]
    assert report["unknown"] == {"Backups": ["software:SW-404"]}
    assert kits.count() == 0 and kit_members.count() == 0


def test_unknown_ids_do_not_abort_the_run(seeded):
    report = seed([{"name": "Ghosts", "members": ["inventory:NOPE", "junk", "software:SW-002"]}])
    assert report["unknown"] == {"Ghosts": ["inventory:NOPE", "junk"]}
    assert report["added"]["Ghosts"] == ["software:s2"]


def test_load_rejects_a_nameless_kit(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"kits": [{"name": " ", "members": []}]}')
    with pytest.raises(ValueError):
        load(p)
