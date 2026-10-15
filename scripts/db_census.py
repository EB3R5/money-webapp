"""Census of a data directory — counts, never rows — and a diff between two censuses.

    scripts/db_census.py --sqlite [--data-dir ./data] [--out census.json]
    scripts/db_census.py --diff before.json after.json          # exit 1 on any difference

Row counts per table, photo entries and document file rows vs Blobs (under the key "files"),
Blob rows and bytes, model presence and sha, sum/min/max over transactions and balances.
Take one before a backup, a restore or a migration and one after; keys under "info" are
reported but not diffed."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _r2(x) -> float:
    return round(float(x or 0), 2)


def _d(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    return str(v)[:10]


def census_sqlite(data_dir: Path) -> dict:
    from app.store.blobs import REFERENCED_SQL
    from app.store.database import Database
    db = Database(Path(data_dir))
    entities = {}
    with db.acquire() as conn:
        for table in db.tables():
            if table == "schema_version":
                continue
            cur = conn.execute(f'SELECT COUNT(*) FROM "{table}"')
            entities[table] = {"rows": int((cur.fetchone())[0])}
        entries = 0
        for table in ("inventory", "software", "kits"):
            if table in entities:
                cur = conn.execute(
                    f"SELECT COALESCE(SUM(json_array_length(images)), 0) FROM {table} WHERE images IS NOT NULL")
                entries += int((cur.fetchone())[0])
        photo_blobs = 0
        if "blobs" in entities:
            cur = conn.execute("SELECT COUNT(*) FROM blobs WHERE kind = 'photo'")
            photo_blobs = int((cur.fetchone())[0])
        cur = conn.execute("SELECT sha256 FROM model_versions LIMIT 1")
        mv = cur.fetchone()
        cur = conn.execute(
            "SELECT COALESCE(SUM(amount), 0), MIN(date), MAX(date) FROM transactions")
        total, mn, mx = cur.fetchone()
        cur = conn.execute("SELECT COALESCE(SUM(balance), 0) FROM balance_history")
        bal = (cur.fetchone())[0]
        doc_rows = doc_blobs = blob_rows = blob_bytes = blob_orphans = 0
        if "documents" in entities:
            cur = conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'file'")
            doc_rows = int((cur.fetchone())[0])
        if "blobs" in entities:
            cur = conn.execute("SELECT COUNT(*) FROM blobs WHERE kind = 'document'")
            doc_blobs = int((cur.fetchone())[0])
            cur = conn.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM blobs")
            blob_rows, blob_bytes = (int(v) for v in cur.fetchone())
            cur = conn.execute(f"SELECT COUNT(*) FROM blobs WHERE id NOT IN ({REFERENCED_SQL})")
            blob_orphans = int((cur.fetchone())[0])
    return {
        "entities": entities,
        "photos": {"entries": entries, "files": photo_blobs},
        "documents": {"file_rows": doc_rows, "files": doc_blobs},
        "blobs": {"rows": blob_rows, "bytes": blob_bytes, "unreferenced": blob_orphans},
        "model": {"present": mv is not None, "sha256": mv[0] if mv else None},
        "transactions": {"sum_amount": _r2(total), "min_date": _d(mn), "max_date": _d(mx)},
        "balance_history": {"sum_balance": _r2(bal)},
        "info": {"source": "sqlite", "data_dir": str(data_dir),
                 "taken_at": datetime.now(UTC).isoformat()},
    }


def diff(a: dict, b: dict) -> list[str]:
    """Human-readable differences, ignoring `info`. Empty means identical."""
    out = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                if k == "info" and not path:
                    continue
                if k not in x:
                    out.append(f"{'.'.join(path + [k])}: missing on left, right={y[k]!r}")
                elif k not in y:
                    out.append(f"{'.'.join(path + [k])}: left={x[k]!r}, missing on right")
                else:
                    walk(x[k], y[k], path + [k])
        elif x != y:
            out.append(f"{'.'.join(path)}: left={x!r} right={y!r}")
    walk(a, b, [])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sqlite", action="store_true")
    g.add_argument("--diff", nargs=2, metavar=("A", "B"))
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.diff:
        a = json.loads(Path(args.diff[0]).read_text())
        b = json.loads(Path(args.diff[1]).read_text())
        d = diff(a, b)
        print("\n".join(d) if d else "census identical")
        return 1 if d else 0
    from app.config import DATA_DIR
    doc = census_sqlite(Path(args.data_dir) if args.data_dir else DATA_DIR)
    text = json.dumps(doc, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
