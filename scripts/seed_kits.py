"""Seed Kits from a JSON file (ADR-0018) in this shape:

    {"kits": [{"name": "Home gym", "description": "…", "how_to": "1. …\\n2. …",
               "members": ["inventory:INV-013", "software:SW-001", …]}, …]}

Members are **business ids** (an Item's Item_ID, a Software's SW_ID), resolved here to the
row ids the `kit_members` table stores. Idempotent by Kit name: a Kit that already exists
keeps its text (the file never overwrites what you edited in the modal) and only gains the
members it is missing, appended in file order; an unknown business id is reported and the
run continues. Runs against DATA_DIR through the stores, like the app.

    .venv/bin/python scripts/seed_kits.py kits.json
    .venv/bin/python scripts/seed_kits.py kits.json --dry-run  # report only, write nothing
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root → import app
from app.config import DATA_DIR  # noqa: E402
from app.store import database  # noqa: E402
from app.store.inventory import inventory  # noqa: E402
from app.store.kit_members import kit_members, member_key  # noqa: E402
from app.store.kits import kits  # noqa: E402
from app.store.software import software  # noqa: E402

# business-id table → (store, the business-id field)
SOURCES = {"inventory": (inventory, "Item_ID"), "software": (software, "SW_ID")}


def load(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data["kits"] if isinstance(data, dict) else data
    for k in rows:
        if not str(k.get("name") or "").strip():
            raise ValueError("every kit needs a name")
    return rows


def business_index() -> dict[str, str]:
    """{'inventory:<Item_ID>': 'inventory:<row id>', 'software:<SW_ID>': 'software:<row id>'}."""
    idx = {}
    for table, (store, field) in SOURCES.items():
        for row in store.list():
            biz = str(row.get(field) or "").strip()
            if biz:
                idx[f"{table}:{biz}"] = member_key(table, row["_id"])
    return idx


def seed(rows: list[dict], *, dry_run: bool = False) -> dict:
    """Apply the seed. Returns a report: per kit what was created / already there, the
    members added, and every business id that named no row."""
    idx = business_index()
    existing = {(k.get("Name") or "").strip().lower(): k for k in kits.list()}
    report = {"created": [], "existing": [], "added": {}, "unknown": {}}
    for k in rows:
        name = k["name"].strip()
        wanted, unknown = [], []
        for biz in k.get("members") or []:
            key = idx.get(str(biz).strip())
            (wanted if key else unknown).append(key or str(biz))
        if unknown:
            report["unknown"][name] = unknown
        kit = existing.get(name.lower())
        if kit is None:
            report["created"].append(name)
            if dry_run:
                report["added"][name] = wanted
                continue
            kit_id = kits.insert({"Name": name, "Description": k.get("description") or None,
                                        "How_To": k.get("how_to") or None})
            existing[name.lower()] = {"_id": kit_id, "Name": name}
        else:
            report["existing"].append(name)
            kit_id = kit["_id"]
        if dry_run:
            have = {r["key"] for r in kit_members.list_for_kit(kit_id)}
            report["added"][name] = [w for w in wanted if w not in have]
        else:
            report["added"][name] = kit_members.add(kit_id, wanted)
    return report


def print_report(report: dict, dry_run: bool) -> None:
    verb = "would create" if dry_run else "created"
    for name in report["created"]:
        print(f"{verb}: {name} (+{len(report['added'].get(name, []))} members)")
    for name in report["existing"]:
        n = len(report["added"].get(name, []))
        print(f"kept: {name} ({'+' + str(n) + ' members' if n else 'nothing to add'})")
    for name, ids in report["unknown"].items():
        print(f"unknown in {name}: {', '.join(ids)}")
    if not report["unknown"]:
        print("every member resolved")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path, help="the kits JSON file")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()
    rows = load(args.file)
    database.configure(DATA_DIR)
    database.init()
    report = seed(rows, dry_run=args.dry_run)
    print_report(report, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
