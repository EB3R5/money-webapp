"""Blobs (app/store/blobs.py, migration 0014): uploads in the database (ADR-0020)."""

import hashlib
import sqlite3

import pytest

from app.store import blobs as mod
from app.store.blobs import blobs
from app.store.database import database


def test_migration_0014_applied(store_db):
    with database.acquire() as conn:
        cur = conn.execute("SELECT MAX(version) FROM schema_version")
        assert (cur.fetchone())[0] >= 14
        cur = conn.execute("PRAGMA table_info(blobs)")
        cols = [r[1] for r in cur.fetchall()]
    assert cols == ["id", "kind", "content_type", "size", "sha256", "created_at", "data"]
    assert cols[-1] == "data", "bytes last so metadata reads never pull the overflow pages"


def test_put_get_meta_delete_round_trip(store_db):
    raw = b"\x89PNG\x00\xff\r\n\x1a\n not utf-8"
    meta = blobs.put("p1", "photo", raw, "image/PNG; charset=binary")
    assert meta["id"] == "p1" and meta["kind"] == "photo" and meta["content_type"] == "image/png"
    assert meta["size"] == len(raw) and meta["sha256"] == hashlib.sha256(raw).hexdigest()
    assert blobs.get("p1") == (raw, "image/png")
    m = blobs.meta("p1")
    assert m["size"] == len(raw) and m["sha256"] == meta["sha256"] and "data" not in m
    assert blobs.delete("p1") is True
    assert blobs.delete("p1") is False
    assert blobs.get("p1") is None and blobs.meta("p1") is None


def test_put_rejects_empty_data_bad_kind_and_unsafe_id(store_db):
    with pytest.raises(ValueError):
        blobs.put("x", "photo", b"", "image/png")
    with pytest.raises(ValueError):
        blobs.put("x", "model", b"abc", None)
    with pytest.raises(ValueError):
        blobs.put("../x", "photo", b"abc", None)
    with pytest.raises(ValueError):
        blobs.put('a"; drop', "photo", b"abc", None)
    assert blobs.get("../x") is None and blobs.delete("../x") is False


def test_get_filters_by_kind_and_duplicate_id_raises(store_db):
    blobs.put("d1", "document", b"%PDF-1.4", "application/pdf")
    assert blobs.get("d1", kind="document") == (b"%PDF-1.4", "application/pdf")
    assert blobs.get("d1", kind="photo") is None
    with pytest.raises(sqlite3.IntegrityError):
        blobs.put("d1", "document", b"other", "application/pdf")
    assert (blobs.get("d1"))[0] == b"%PDF-1.4", "the first write stands"


def test_new_photo_mints_entry_and_filename_fallback(store_db):
    e = blobs.new_photo(b"\x89PNG...", "image/png", "orig.png")
    assert len(e["id"]) == 32 and e == {"id": e["id"], "filename": "orig.png", "content_type": "image/png"}
    assert blobs.get(e["id"], kind="photo") == (b"\x89PNG...", "image/png")
    e2 = blobs.new_photo(b"x", None)
    assert e2["filename"] == f"{e2['id']}.bin" and e2["content_type"] == "application/octet-stream"
    assert (blobs.meta(e2["id"]))["kind"] == "photo"


def test_ids_and_totals(store_db):
    assert blobs.totals() == {"photo": 0, "document": 0, "bytes": 0}
    blobs.put("b", "photo", b"12345", "image/png")
    blobs.put("a", "photo", b"12", "image/png")
    blobs.put("c", "document", b"1", "application/pdf")
    assert blobs.ids() == ["a", "b", "c"]
    assert blobs.ids(kind="document") == ["c"]
    assert blobs.totals() == {"photo": 2, "document": 1, "bytes": 8}


def test_extension_allow_list():
    assert mod.extension_for("image/jpeg; charset=binary") == "jpg"
    assert mod.extension_for("application/pdf") == "bin"
    assert mod.extension_for(None) == "bin"


def test_document_ext_allow_list():
    assert mod.document_ext("Report.PDF") == "pdf"
    assert mod.document_ext("x.tar.gz") == "gz"
    assert mod.document_ext("noext") == "bin"
    assert mod.document_ext("we ird.t xt") == "bin"
    assert mod.document_ext("../../evil.html") == "html"    # only the suffix is used
    assert mod.document_ext(None) == "bin"


# --- the image route on every photo-bearing collection ---------------------------------

@pytest.mark.parametrize("slug, row_id, store_name", [
    ("inventory", "inv1", "inventory"), ("software", "s1", "software"), ("kits", "k1", "kits")])
def test_photo_round_trip_on_every_slug(store_client, slug, row_id, store_name):
    import importlib
    from tests import dbhelper
    dbhelper.seed_inventory()
    dbhelper.seed_software()
    from app.store.kits import kits
    kits.insert({"_id": "k1", "Name": "Home gym"})
    store = getattr(importlib.import_module(f"app.store.{store_name}"), store_name)

    r = store_client.post(f"/api/{slug}/{row_id}/images",
                                files=[("files", ("p.png", b"\x89PNG-bytes", "image/png"))])
    entry = r.json()["images"][0]
    assert (store.get(row_id))["_images"] == [entry]
    r = store_client.get(f"/api/{slug}/image/{entry['id']}")
    assert r.status_code == 200 and r.content == b"\x89PNG-bytes"
    assert not (database.data_dir / "photos").exists(), "no files beside the database"
    r = store_client.post(f"/api/{slug}/{row_id}/images/delete", json={"id": entry["id"]})
    assert r.json() == {"ok": True}
    assert blobs.get(entry["id"]) is None
    assert (store.get(row_id))["_images"] == []
