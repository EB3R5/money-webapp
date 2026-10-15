"""scripts/db_census.py: the SQLite census and the diff."""

import json

from app.store.blobs import blobs
from app.store.documents import documents
from app.store.inventory import inventory
from app.store.transactions import transactions
from scripts import db_census


def test_sqlite_census_counts_rows_photos_and_sums(store_db):
    transactions.insert_many([
        {"_id": "a", "Amount": -4.5, "Date": "2026-01-03"},
        {"_id": "b", "Amount": 10, "Date": "2026-01-01"},
    ])
    e = blobs.new_photo(b"x", "image/png")
    inventory.insert({"_id": "i1", "Item_Name": "Lamp", "_images": [e]})
    blobs.put("doc1", "document", b"%PDF", "application/pdf")
    documents.insert({"_id": "doc1", "parent_table": "inventory", "parent_id": "i1",
                            "name": "manual.pdf", "kind": "file", "file_ext": "pdf", "size": 4})
    documents.insert({"parent_table": "inventory", "parent_id": "i1", "name": "n.md",
                            "kind": "md", "body": "", "size": 0})
    c = db_census.census_sqlite(store_db)
    assert c["entities"]["transactions"]["rows"] == 2
    assert c["entities"]["inventory"]["rows"] == 1
    assert c["photos"] == {"entries": 1, "files": 1}
    assert c["documents"] == {"file_rows": 1, "files": 1}
    assert c["blobs"] == {"rows": 2, "bytes": 5, "unreferenced": 0}
    assert c["model"] == {"present": False, "sha256": None}
    assert c["transactions"] == {"sum_amount": 5.5, "min_date": "2026-01-01", "max_date": "2026-01-03"}
    assert "schema_version" not in c["entities"]
    json.dumps(c)  # JSON-safe


def test_diff_reports_changes_and_ignores_info():
    a = {"entities": {"t": {"rows": 1}}, "photos": {"entries": 1, "files": 1},
         "info": {"source": "sqlite", "taken_at": "x"}}
    b = {"entities": {"t": {"rows": 2}}, "photos": {"entries": 1, "files": 1},
         "info": {"source": "sqlite", "taken_at": "y"}}
    d = db_census.diff(a, b)
    assert d == ["entities.t.rows: left=1 right=2"]
    b["entities"]["t"]["rows"] = 1
    assert db_census.diff(a, b) == []
    assert db_census.diff(a, {"entities": {}, "photos": a["photos"]}) == \
        ["entities.t: left={'rows': 1}, missing on right"]
