"""Seed and read the SQLite stores in tests with API-shaped dicts (ADR-0011 addendum).

The stores already speak API keys ("Account #", "Pred:Conf") and translate through their
field maps, so this helper is thin: a shared seed for the ledger-shaped fixtures, plus
`seed`/`one`/`get` so a test never writes SQL or a column name. Everything goes through the
`database` handle the `store_db` fixture re-points at the test's own data directory."""

from datetime import datetime

from app.store.accounts import accounts
from app.store.balance_history import balance_history
from app.store.base import Store
from app.store.categories import categories
from app.store.documents import documents
from app.store.inventory import inventory
from app.store.software import software
from app.store.transactions import transactions

# The shared seed rows, in API shape. Category ids are the
# Category name (as in the Mongo era); the ledger cascade looks them up by Category.
SEED_CATEGORIES = [
    {"_id": "Auto", "Category": "Auto", "Group": "Transport", "Budget": "Variable",
     "Cashflow Type": "Expense", "Timing": "Monthly", "Type": "Spend"},
    {"_id": "Food", "Category": "Food", "Group": "Variable", "Budget": "Variable",
     "Cashflow Type": "Expense", "Timing": "Monthly", "Type": "Spend"},
]
SEED_TRANSACTIONS = [
    {"_id": "t1", "Date": datetime(2024, 5, 1), "Description": "Coffee",
     "Category": "Food", "Group": "Variable", "Amount": -4.5,
     "Account": "Visa", "Institution": "Chase"},
    {"_id": "t2", "Date": datetime(2024, 5, 2), "Description": "Paycheck",
     "Category": "Income", "Group": "Income", "Amount": 2000.0,
     "Account": "Checking", "Institution": "Ally"},
    {"_id": "t3", "Date": datetime(2024, 5, 3), "Description": "Rent",
     "Category": "Housing", "Group": "Fixed", "Amount": -1500.0,
     "Account": "Checking", "Institution": "Ally"},
]
SEED_ACCOUNTS = [
    {"_id": "acc1", "Account ID": "A1", "Account": "Checking", "Type": "Assets",
     "Amount": 1000.0, "Category": "Bank", "Status": "Open"},
    {"_id": "acc2", "Account ID": "A2", "Account": "Visa", "Type": "Liabilities",
     "Amount": -500.0, "Status": "Open"},
    {"_id": "acc3", "Account ID": "A3", "Account": "Old Card", "Type": "Liabilities",
     "Amount": -10.0, "Status": "Closed"},
    {"_id": "acc4", "Account ID": "A4", "Account": "", "Type": "Assets",
     "Amount": 0.0, "Status": "Open"},  # nameless placeholder — must be skipped
]
SEED_BALANCES = [
    {"_id": "b1", "Date": datetime(2024, 1, 2), "Account": "Checking", "Account ID": "A1",
     "Institution": "Ally", "Class": "Asset", "Account Type": "Checking", "Balance": 100.0},
    {"_id": "b2", "Date": datetime(2024, 2, 2), "Account": "Visa", "Account ID": "A2",
     "Institution": "Chase", "Class": "Liability", "Account Type": "Credit", "Balance": -50.0},
]
SEED_INVENTORY = [
    {"_id": "inv1", "Item_ID": "X1", "Item_Name": "Drill", "Category": "Tools",
     "Qty": 2, "Unit_Cost": 50, "Brand": "Bosch"},
    {"_id": "inv2", "Item_ID": "X2", "Item_Name": "Pen", "Category": "Office",
     "Qty": 10, "Unit_Cost": 1},
]
SEED_SOFTWARE = [
    # s1: a paid subscription (the only monthly cost → grand total $10), Category Audio.
    {"_id": "s1", "SW_ID": "SW-001", "Item_Name": "Obsidian Sync", "Status": "using",
     "Kind": "saas", "Vendor": "Obsidian", "Category": "Audio", "License_Type": "subscription",
     "Billing_Cadence": "monthly", "Cost": 10.0, "Currency": "USD",
     "Link": "https://obsidian.md/sync"},
    # s2: imported from this box's pacman, automatic status, a newer upstream version known.
    {"_id": "s2", "SW_ID": "SW-002", "Item_Name": "ripgrep", "Status": "using",
     "_import_status": "using", "Kind": "cli", "Vendor": "BurntSushi", "License_Type": "oss",
     "License_Id": "Unlicense", "Source_Key": "pacman:ripgrep",
     "Repo_URL": "https://github.com/BurntSushi/ripgrep", "Link": "https://github.com/BurntSushi/ripgrep",
     "Version_Installed": "14.1.1", "Version_Latest": "14.1.2", "Stars": 50000,
     "Install_Locations": [{"host": "workstation", "manager": "pacman", "id": "ripgrep",
                            "version": "14.1.1", "seen_at": "2026-09-01T00:00:00Z"}]},
    # s3: gone from every host (hidden from the active view).
    {"_id": "s3", "SW_ID": "SW-003", "Item_Name": "Old Editor", "Status": "uninstalled",
     "_import_status": "uninstalled", "Kind": "app", "Install_Locations": []},
]


def seed(store: Store, rows: list[dict]) -> list[str]:
    """Insert API-shaped rows; ids come from `_id` when given."""
    return store.insert_many(rows)


def seed_ledger() -> None:
    """Categories + transactions every ledger-shaped test starts from."""
    seed(categories, SEED_CATEGORIES)
    seed(transactions, SEED_TRANSACTIONS)


def seed_accounts() -> None:
    """The four seeded account cards (Checking / Visa / Old Card / a nameless placeholder)."""
    seed(accounts, SEED_ACCOUNTS)


def seed_balances() -> None:
    """Accounts + balance Snapshots the Balances tests start from."""
    seed_accounts()
    seed(balance_history, SEED_BALANCES)


def seed_inventory() -> None:
    """The two seeded Items (Tools / Office)."""
    seed(inventory, SEED_INVENTORY)


def seed_software() -> None:
    """The three seeded Software items (a subscription, a pacman import, an uninstalled app)."""
    seed(software, SEED_SOFTWARE)


def get(store: Store, id_: str) -> dict | None:
    return store.get(id_)


def one(store: Store, **where) -> dict | None:
    """First row matching API-key equality filters, e.g. one(deletions, collection="transactions")."""
    return store.one(where)


def routes(patterns) -> list:
    """The route strings of a view module (its `urlpatterns`) or a pattern list, in order:
    "/api/inventory/<str:doc_id>/images". What the old router-inspection tests read."""
    pats = getattr(patterns, "urlpatterns", patterns)
    return ["/" + str(p.pattern) for p in pats]
