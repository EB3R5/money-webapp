"""Inventory → Balance Sheet sync: take the category rollup, keep the
top-N categories by cost share as individual line items, aggregate the rest into one
"Other Inventory" entry, map each to a balance-sheet category/group/type as Current
Assets, and write them into the `balanceHistory` collection so what you own shows up
on the balance sheet.

Every sync appends dated records (_src == "inventory_sync") — earlier snapshots stay
in balanceHistory as history, so the balance sheet can read within-month movement.
"""

from datetime import UTC, datetime

from . import snapshot

SYNC_SRC = "inventory_sync"
INSTITUTION_NAME = "Inventory"
ACCOUNT_PREFIX = "INV"
TOP_N_CATEGORIES = 8
AGGREGATED_LABEL = "Other Inventory"

# Inventory category -> balance-sheet {category, group, type}.
INVENTORY_CATEGORY_MAP = {
    "Electronics":         {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Furniture":           {"category": "Furniture & Fixtures", "group": "Property & Equipment", "type": "Assets"},
    "Vehicles":            {"category": "Vehicles", "group": "Property & Equipment", "type": "Assets"},
    "Home Appliances":     {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Kitchen Appliances":  {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Kitchen Appliance":   {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Kitchen Equipment":   {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Kitchen & Dining":    {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Kitchen Storage":     {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Kitchenware":         {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Fitness Equipment":   {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Musical Instruments": {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Photography":         {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Tools":               {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Fans":                {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Sports":              {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Sports & Fitness":    {"category": "Equipment", "group": "Property & Equipment", "type": "Assets"},
    "Computer":            {"category": "Computer", "group": "Property & Equipment", "type": "Assets"},
    "Clothing":            {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Footwear":            {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Accessories":         {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Home & Kitchen":      {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Home Goods":          {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Dining":              {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Cleaning Supplies":   {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Air Filters":         {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Health & Safety":     {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Personal Care":       {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Media":               {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Travel":              {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Travel Accessories":  {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
    "Other Inventory":     {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"},
}
DEFAULT_MAPPING = {"category": "Other Current Assets", "group": "Current Assets", "type": "Assets"}


def resolve_mapping(category):
    return INVENTORY_CATEGORY_MAP.get(category, DEFAULT_MAPPING)


def consolidate(rollup_rows):
    """Top-N inventory categories by cost share as line items; rest → 'Other Inventory'.
    `rollup_rows` are the per-category dicts from reports._inventory_rollup."""
    rows = sorted(rollup_rows, key=lambda r: r["pct"], reverse=True)
    top = rows[:TOP_N_CATEGORIES]
    rest = rows[TOP_N_CATEGORIES:]
    items = [{"category": r["category"], "cost": round(r["cost"], 2)} for r in top]
    if rest:
        items.append({"category": AGGREGATED_LABEL,
                      "cost": round(sum(r["cost"] for r in rest), 2)})
    return items


def build_balance_doc(item, when=None):
    """Map one consolidated inventory line to a balanceHistory Snapshot
    (shape owned by app/snapshot.py)."""
    cat = item["category"]
    m = resolve_mapping(cat)
    when = when or datetime.now(UTC)
    return snapshot.snapshot_doc(
        _id=f"invsync_{snapshot.slug(cat)}_{int(when.timestamp() * 1_000_000)}",
        account=cat,
        balance=item["cost"],
        category=m["category"],
        group=m["group"],
        type_=m["type"],            # "Assets" → groups under Assets on the balance sheet
        account_type=m["category"],  # Balances grid "Account Type" column
        cls="Assets",
        institution=INSTITUTION_NAME,
        acct_id=snapshot.account_id(INSTITUTION_NAME, "inventory", cat),
        src=SYNC_SRC,
        when=when,
    )


def sync_inventory_to_balances(rollup_rows):
    """Record the current inventory rollup in balanceHistory as new dated rows.
    Returns a summary: line count, total cost, and the line-item account names."""
    when = datetime.now(UTC)
    items = consolidate(rollup_rows)
    docs = [build_balance_doc(it, when) for it in items]
    return snapshot.append(SYNC_SRC, docs)
