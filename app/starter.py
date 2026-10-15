"""What a fresh database starts with (open-source readiness): the **starter taxonomies** in
app/seeds/ — the ledger Categories with the derived fields the cascade needs (ADR-0006), the
balance-sheet account categories the Balances page and the balance sheet read, and the
inventory categories the Inventory pages flip through. Each file is written once, when its
own table is empty; a table with any row is never touched. Edit the rows on the Categories
page afterwards; edit a file to change what a new install gets."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .store.account_categories import account_categories
from .store.base import Store
from .store.categories import categories
from .store.inventory_categories import inventory_categories

log = logging.getLogger("money.starter")

SEEDS_DIR = Path(__file__).resolve().parent / "seeds"
SEED_FILE = SEEDS_DIR / "categories.json"                     # the ledger taxonomy (tests patch it)

# The ledger taxonomy's vocabulary, in the words the reports read.
FIELDS = ("Category", "Group", "Type", "Budget", "Cashflow Type", "Timing")
TYPES = ("Income", "Expense", "Transfer")
BUDGETS = ("Discretionary", "Non-Discretionary")
CASHFLOWS = ("Operating Activities", "Investing Activities", "Financing Activities", "Fixed Asset Activities")
TIMINGS = ("Monthly", "Weekly", "Quarterly", "Semi Yearly", "Yearly", "One-Time")

# The balance-sheet taxonomy: the coarse kind app/networth.py reduces (Equity counts with Assets).
ACCOUNT_FIELDS = ("Category", "Group", "Type")
ACCOUNT_TYPES = ("Assets", "Liabilities", "Equity")
# The Add-account presets (app/views/accounts.py ACCOUNT_TYPES) name these; the seed must carry them.
ACCOUNT_PRESETS = ("Checking Account", "Credit Card Debt", "Common Stock", "Loan")

# The inventory taxonomy: two descriptive lists that never cascade onto Items.
INVENTORY_FIELDS = ("Category", "Group", "Subcategory", "Classification")
CLASSIFICATIONS = ("Apparel", "Accessory", "Technology", "Equipment", "Furniture", "Home Goods",
                   "Kitchen Equipment", "Media", "Consumable", "Supply", "Asset")


def _rows(path: Path, key: str, fields: tuple, what: str) -> list[dict]:
    """The rows of a seed file, checked: every field present and no item twice. A bad file
    is a loud error, not a half-seeded database."""
    rows = json.loads(path.read_text())[key]
    seen = set()
    for r in rows:
        missing = [f for f in fields if not r.get(f)]
        if missing:
            raise ValueError(f"starter {what} {r.get('Category')!r}: missing {missing}")
        if r["Category"] in seen:
            raise ValueError(f"starter {what} {r['Category']!r} twice")
        seen.add(r["Category"])
    return rows


def _check_vocab(rows: list[dict], what: str, *checks: tuple[str, tuple]) -> None:
    for r in rows:
        for field, allowed in checks:
            if r[field] not in allowed:
                raise ValueError(f"starter {what} {r['Category']!r}: {field} {r[field]!r} not in {allowed}")


def load_starter_categories() -> list[dict]:
    rows = _rows(SEED_FILE, "categories", FIELDS, "category")
    _check_vocab(rows, "category", ("Type", TYPES), ("Budget", BUDGETS), ("Cashflow Type", CASHFLOWS), ("Timing", TIMINGS))
    return rows


def load_starter_account_categories() -> list[dict]:
    rows = _rows(SEEDS_DIR / "account_categories.json", "account_categories", ACCOUNT_FIELDS, "account category")
    _check_vocab(rows, "account category", ("Type", ACCOUNT_TYPES))
    missing = [p for p in ACCOUNT_PRESETS if p not in {r["Category"] for r in rows}]
    if missing:
        raise ValueError(f"starter account categories lack the Add-account presets {missing}")
    return rows


def load_starter_inventory_categories() -> list[dict]:
    rows = _rows(SEEDS_DIR / "inventory_categories.json", "inventory_categories", INVENTORY_FIELDS, "inventory category")
    for r in rows:
        bad = [c for c in (x.strip() for x in r["Classification"].split(",")) if c not in CLASSIFICATIONS]
        if bad:
            raise ValueError(f"starter inventory category {r['Category']!r}: Classification {bad} not in {CLASSIFICATIONS}")
    return rows


def _seed(store: Store, load, what: str) -> int:
    """Write a starter taxonomy when its table has no rows at all. Returns how many rows
    were written: 0 means the table already had rows and was left as it is."""
    if store.count() > 0:
        log.info("%s exist; the starter taxonomy is not written", what)
        return 0
    rows = load()
    store.insert_many([{"_id": r["Category"], **r} for r in rows])
    log.info("fresh database: %d starter %s written", len(rows), what)
    return len(rows)


def seed_categories() -> int:
    return _seed(categories, load_starter_categories, "categories")


def seed_account_categories() -> int:
    return _seed(account_categories, load_starter_account_categories, "account categories")


def seed_inventory_categories() -> int:
    return _seed(inventory_categories, load_starter_inventory_categories, "inventory categories")


def seed_all() -> dict[str, int]:
    """Every starter taxonomy, each on its own table's emptiness: {what: rows written}."""
    return {"categories": seed_categories(),
            "account categories": seed_account_categories(),
            "inventory categories": seed_inventory_categories()}
