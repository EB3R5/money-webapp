"""Remove Blobs nothing references (ADR-0020, ADR-0005 addendum).

A Blob outlives its owner: deleting an Item, a Software row or a Kit leaves its photo and
file-Document Blobs so a row restored from `deletions` finds its bytes. This lists — and with
`--apply` deletes — every Blob that no live row (`_images` entries of inventory, software,
kits; file Documents) and no deletion snapshot names any more, then VACUUMs so the space
comes back. Counts and ids only; never prints bytes.

    .venv/bin/python scripts/prune_blobs.py                      # dry run: list, delete nothing
    .venv/bin/python scripts/prune_blobs.py --apply              # delete, then VACUUM
    .venv/bin/python scripts/prune_blobs.py --apply --no-vacuum

`--apply` needs the app stopped: VACUUM rewrites the database file and wants about twice its
size free on disk."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root → import app
from app.config import DATA_DIR  # noqa: E402
from app.store import database  # noqa: E402
from app.store.blobs import blobs  # noqa: E402

CHUNK = 500


def prune(data_dir: Path, *, apply: bool, vacuum: bool = True) -> dict:
    """Returns {"victims": [meta…], "deleted": n, "pages_before": n, "pages_after": n}."""
    database.configure(Path(data_dir))
    database.init()
    victims = blobs.unreferenced()
    rep = {"victims": victims, "deleted": 0, "pages_before": None, "pages_after": None}
    if not apply:
        return rep
    ids = [v["id"] for v in victims]
    with database.scope() as conn:
        for i in range(0, len(ids), CHUNK):
            chunk = ids[i:i + CHUNK]
            marks = ", ".join("?" for _ in chunk)
            cur = conn.execute(f"DELETE FROM blobs WHERE id IN ({marks})", chunk)
            rep["deleted"] += cur.rowcount
    if vacuum:
        # VACUUM cannot run inside a transaction: a fresh autocommit connection, outside any scope.
        conn = sqlite3.connect(database.path, isolation_level=None)
        try:
            rep["pages_before"] = conn.execute("PRAGMA page_count").fetchone()[0]
            conn.execute("VACUUM")
            rep["pages_after"] = conn.execute("PRAGMA page_count").fetchone()[0]
        finally:
            conn.close()
    return rep


def print_report(rep: dict, apply: bool) -> None:
    victims = rep["victims"]
    total = sum(int(v.get("size") or 0) for v in victims)
    verb = "deleted" if apply else "unreferenced"
    print(f"{verb}: {len(victims) if not apply else rep['deleted']} blobs, {total:,} bytes")
    for v in victims:
        print(f"  {v['id']}  {v['kind']}  {int(v.get('size') or 0):,}  {v.get('created_at') or ''}")
    if rep["pages_before"] is not None:
        print(f"vacuum: {rep['pages_before']:,} -> {rep['pages_after']:,} pages")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=DATA_DIR, type=Path)
    ap.add_argument("--apply", action="store_true", help="delete the unreferenced Blobs (app stopped)")
    ap.add_argument("--no-vacuum", action="store_true", help="with --apply: skip the VACUUM")
    args = ap.parse_args()
    rep = prune(args.data_dir, apply=args.apply, vacuum=not args.no_vacuum)
    print_report(rep, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
