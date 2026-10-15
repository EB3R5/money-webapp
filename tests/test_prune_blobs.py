"""scripts/prune_blobs.py and blobs.referenced_ids: a Blob is kept while any live row or any
deletion snapshot names it (ADR-0005 addendum); the rest goes, then VACUUM."""

from app.store.blobs import blobs
from app.store.database import database
from app.store.deletions import deletions
from app.store.documents import documents
from app.store.inventory import inventory
from app.store.kits import kits
from app.store.software import software
from scripts import prune_blobs as pr


def _world():
    """a: Item photo; b: Kit photo; c: live file Document; d: only in an Item deletion
    snapshot; e: only in a Document deletion snapshot; f: nowhere; g: Software photo."""
    for i in "abcdefg":
        blobs.put(i, "document" if i in "ce" else "photo", i.encode() * 3, "image/png")
    inventory.insert({"_id": "inv1", "Item_Name": "Drill", "_images": [{"id": "a"}]})
    inventory.insert({"_id": "inv2", "Item_Name": "Pen", "_images": None})
    software.insert({"_id": "s1", "Item_Name": "App", "_images": [{"id": "g", "filename": "g.png"}]})
    kits.insert({"_id": "k1", "Name": "Gym", "_images": [{"id": "b"}]})
    documents.insert({"_id": "c", "parent_table": "inventory", "parent_id": "inv1",
                            "name": "m.pdf", "kind": "file", "content_type": "application/pdf", "size": 3})
    documents.insert({"_id": "n1", "parent_table": "inventory", "parent_id": "inv1",
                            "name": "n.md", "kind": "md", "body": "", "size": 0})
    deletions.log("inventory", [{"_id": "gone", "Item_Name": "Old", "_images": [{"id": "d"}]},
                                      {"_id": "gone2", "Item_Name": "No photos"}])
    deletions.log("documents", [{"_id": "e", "kind": "file", "file_ext": "pdf", "name": "w.pdf"},
                                      {"_id": "oldnote", "kind": "md", "name": "x.md"}])
    deletions.log("transactions", [{"_id": "t1", "_images": [{"id": "f"}]}])   # not a photo table: ignored


def test_referenced_ids_sees_live_rows_and_snapshots(store_db):
    _world()
    assert blobs.referenced_ids() == {"a", "b", "c", "d", "e", "g"}
    assert [v["id"] for v in blobs.unreferenced()] == ["f"]


def test_dry_run_lists_and_deletes_nothing(store_db):
    _world()
    rep = pr.prune(store_db, apply=False)
    assert [v["id"] for v in rep["victims"]] == ["f"] and rep["deleted"] == 0
    assert rep["pages_before"] is None
    assert (blobs.totals())["photo"] == 5


def test_apply_deletes_exactly_the_unreferenced_set_and_vacuums(store_db):
    _world()
    big = b"x" * 200_000
    for i in range(5):                                   # enough pages for VACUUM to give back
        blobs.put(f"orphan{i}", "photo", big, "image/png")
    rep = pr.prune(store_db, apply=True)
    assert rep["deleted"] == 6 and sorted(v["id"] for v in rep["victims"]) == ["f", *(f"orphan{i}" for i in range(5))]
    assert blobs.ids() == ["a", "b", "c", "d", "e", "g"]
    assert rep["pages_before"] > rep["pages_after"]
    with database.acquire() as conn:
        cur = conn.execute("PRAGMA freelist_count")
        assert (cur.fetchone())[0] == 0


def test_no_vacuum_flag(store_db):
    _world()
    rep = pr.prune(store_db, apply=True, vacuum=False)
    assert rep["deleted"] == 1 and rep["pages_before"] is None
    assert blobs.get("f") is None
