"""The SQLite store layer (app/store): schema, the shared handle, and the base CRUD.

Each test gets its own DATA_DIR under tmp_path; the module-level `database` object is
re-pointed there by the `store_db` fixture (ADR-0011 addendum) and the schema applied by
the same `init()` production uses."""

import importlib
import json
import pkgutil
from datetime import UTC, date, datetime

import pytest

from app import store as store_pkg
from app.store import database
from app.store.base import Field, Store
from app.store.transactions import transactions
from app.store.inventory import inventory
from app.store.portfolio import portfolio
from app.store.budgets import budgets
from app.store.budget_lines import budget_lines
from app.store.deletions import deletions
from app.store.health_periods import health_periods
from app.store.metrics_config import metrics_config

EXPECTED_TABLES = {
    "schema_version", "transactions", "categories", "autocat", "accounts", "balance_history",
    "account_categories", "inventory", "inventory_categories", "portfolio", "budgets",
    "budget_lines", "credit_accounts", "credit_scores", "credit_activity",
    "savings_category_mapping", "tax_category_mapping", "tax_history", "savings_goals",
    "health_periods", "metrics_config", "deletions", "model_versions", "app_health",
    "connections", "sync_runs", "sync_cursors", "documents", "software", "kits", "kit_members",
    "blobs", "journal_entries", "expected_flows",
}
LATEST = 18


def _entity_stores():
    """Every Store instance declared by an app.store.<entity> module."""
    out = []
    for m in pkgutil.iter_modules(store_pkg.__path__):
        if m.name in ("base", "database"):
            continue
        mod = importlib.import_module(f"app.store.{m.name}")
        for v in vars(mod).values():
            if isinstance(v, Store):
                out.append(v)
    return out


# --- schema & handle ---------------------------------------------------------------

def test_init_creates_every_table_and_records_version(store_db):
    assert set(database.tables()) == EXPECTED_TABLES
    with database.acquire() as conn:
        v = database.current_version(conn)
    assert v == LATEST
    assert (store_db / "money.sqlite").exists()


def test_init_upgrades_an_existing_database(tmp_path):
    """A data directory at schema version 1 gains the later files on the next start."""
    from app.store.database import Database
    db = Database(tmp_path / "data")
    only_first = [f for f in db.schema_files() if f[0] == 1]
    db.schema_files = lambda: only_first            # pretend only 0001 existed at first run
    assert db.init() == 1
    del db.schema_files
    assert db.init() == LATEST
    with db.acquire() as conn:
        cols = {r["name"] for r in (conn.execute('PRAGMA table_info("autocat")')).fetchall()}
    assert {"order", "enabled"} <= cols


def test_init_is_idempotent(store_db):
    assert database.init() == LATEST
    assert database.init() == LATEST


def test_every_store_column_exists_in_schema(store_db):
    with database.acquire() as conn:
        for s in _entity_stores():
            cur = conn.execute(f'PRAGMA table_info("{s.table}")')
            cols = {r["name"] for r in cur.fetchall()}
            missing = set(s.columns) - cols
            assert not missing, f"{s.table}: columns {missing} not in schema"
            if s.spill:
                assert s.spill in cols, f"{s.table}: spill column {s.spill} missing"


def test_pragmas(store_db):
    with database.acquire() as conn:
        jm = ((conn.execute("PRAGMA journal_mode")).fetchone())[0]
        fk = ((conn.execute("PRAGMA foreign_keys")).fetchone())[0]
    assert jm == "wal" and fk == 1


def test_scope_shares_one_connection_and_rolls_back(store_db):
    with database.scope() as outer:
        with database.acquire() as inner:
            assert inner is outer
    with pytest.raises(RuntimeError):
        with database.scope():
            transactions.insert({"Description": "doomed", "Amount": 1})
            raise RuntimeError("abort")
    assert transactions.count() == 0


# --- field map ----------------------------------------------------------------------

def test_to_row_maps_api_keys_and_types():
    row, leftovers = transactions.to_row({
        "_id": "t1", "Account #": "1234", "Amount": "-$1,234.50", "Date": date(2026, 6, 1),
        "Pred:Conf": {"a": 0.5}, "col1": "junk",
    })
    assert row["id"] == "t1"
    assert row["account_number"] == "1234"
    assert row["amount"] == -1234.5
    assert row["date"] == "2026-06-01T00:00:00"
    assert json.loads(row["pred_conf"]) == {"a": 0.5}
    assert leftovers == {"col1": "junk"}


def test_to_row_strict_rejects_unknown_keys():
    with pytest.raises(ValueError):
        transactions.to_row({"Nope": 1}, strict=True)


def test_real_parsing_handles_percent_and_parens():
    from app.store.base import _to_db
    assert _to_db("real", "12.5%") == 12.5
    assert _to_db("real", "(300)") == -300.0
    assert _to_db("real", "") is None
    assert _to_db("bool", "true") == 1 and _to_db("bool", 0) == 0
    assert _to_db("int", "1,200") == 1200


def test_field_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Field("x", "x", "blob")


# --- CRUD -------------------------------------------------------------------------

def test_insert_get_roundtrip_with_types(store_db):
    tid = transactions.insert({
        "_id": "t1", "Transaction ID": "TX-1", "Date": datetime(2026, 6, 1, tzinfo=UTC),
        "Description": "Coffee", "Amount": "-4.50", "Account": "Checking",
        "Pred:Conf": {"Coffee": 0.9},
    })
    assert tid == "t1"
    d = transactions.get("t1")
    assert d["_id"] == "t1" and d["id"] == "t1"
    assert d["Amount"] == -4.5
    assert isinstance(d["Date"], datetime) and d["Date"].year == 2026
    assert d["Pred:Conf"] == {"Coffee": 0.9}
    assert isinstance(d["_created_at"], datetime)
    assert d["_edited_at"] is None


def test_insert_assigns_uuid_when_no_id(store_db):
    id_ = inventory.insert({"Item_Name": "Drill", "Qty": "2", "Unit_Cost": "300"})
    assert len(id_) == 32
    d = inventory.get(id_)
    assert d["Qty"] == 2.0 and d["Unit_Cost"] == 300.0


def test_update_is_dirty_diff_and_stamps_edited_at(store_db):
    inventory.insert({"_id": "i1", "Item_Name": "Drill", "Brand": "Bosch", "Qty": 1})
    assert inventory.update("i1", {"Qty": 3})
    d = inventory.get("i1")
    assert d["Qty"] == 3.0 and d["Brand"] == "Bosch"
    assert isinstance(d["_edited_at"], datetime)
    assert not inventory.update("missing", {"Qty": 1})


def test_json_list_column_roundtrip(store_db):
    imgs = [{"id": "abc", "filename": "a.png", "content_type": "image/png"}]
    inventory.insert({"_id": "i1", "Item_Name": "Lamp", "_images": imgs})
    assert (inventory.get("i1"))["_images"] == imgs


def test_bool_and_percent_on_portfolio(store_db):
    portfolio.insert({"_id": "p1", "Asset": "VTI", "Shares": "12.5", "Delta": "0.0123",
                            "_closed": True, "Current Value": "$3,605.29"})
    d = portfolio.get("p1")
    assert d["_closed"] is True and d["Shares"] == 12.5 and d["Current Value"] == 3605.29


def test_spill_column_keeps_open_ended_fields(store_db):
    health_periods.insert({"_id": "h1", "period": "2026-Q1", "cash": 1000, "revenue": 5000,
                                 "scores": {"liquidity": 80}})
    d = health_periods.get("h1")
    assert d["period"] == "2026-Q1" and d["cash"] == 1000 and d["scores"] == {"liquidity": 80}
    health_periods.update("h1", {"cash": 1500})
    d = health_periods.get("h1")
    assert d["cash"] == 1500 and d["revenue"] == 5000, "spill update merges, never clobbers"


def test_config_doc_spill_only_store(store_db):
    metrics_config.insert({"_id": "credit", "score_target": 800})
    assert (metrics_config.get("credit"))["score_target"] == 800


def test_delete_returns_row_and_deletions_store_snapshots(store_db):
    transactions.insert({"_id": "t1", "Description": "x", "Amount": 1})
    gone = transactions.delete("t1")
    deletions.insert({"collection": "transactions", "doc": gone, "deleted_at": datetime.now(UTC)})
    assert transactions.get("t1") is None
    logged = deletions.one({"collection": "transactions"})
    assert logged["doc"]["Description"] == "x"
    assert transactions.delete("t1") is None


def test_upsert_protects_app_owned_fields(store_db):
    transactions.insert({"_id": "t1", "Description": "old", "Amount": 1, "Category": "Coffee"})
    transactions.upsert({"_id": "t1", "Description": "new", "Amount": 2, "Category": "Sheet"},
                              protect=("Category",))
    d = transactions.get("t1")
    assert d["Description"] == "new" and d["Amount"] == 2 and d["Category"] == "Coffee"
    transactions.upsert({"_id": "t2", "Description": "fresh", "Amount": 3, "Category": "Sheet"},
                              protect=("Category",))
    assert (transactions.get("t2"))["Category"] == "Sheet", "protect never blocks an insert"


# --- queries ----------------------------------------------------------------------

def _seed_ledger():
    transactions.insert_many([
        {"_id": "a", "Description": "Coffee shop", "Amount": -4, "Category": "Coffee", "Date": "2026-01-03"},
        {"_id": "b", "Description": "Grocery", "Amount": -40, "Category": "Food", "Date": "2026-01-02"},
        {"_id": "c", "Description": "Paycheck", "Amount": 1000, "Category": "Income", "Date": "2026-01-01"},
    ])


def test_list_where_order_limit(store_db):
    _seed_ledger()
    rows = transactions.list(order=[("Date", "asc")])
    assert [r["_id"] for r in rows] == ["c", "b", "a"]
    rows = transactions.list({"Category": ["Coffee", "Food"]}, order=[("Amount", "desc")], limit=1)
    assert [r["_id"] for r in rows] == ["a"]
    assert transactions.count({"Category": "Income"}) == 1
    assert transactions.one({"Category": None}) is None
    assert transactions.distinct("Category") == ["Coffee", "Food", "Income"]


def test_search_is_case_insensitive_like_with_total(store_db):
    _seed_ledger()
    rows, total = transactions.search("COFFEE", ["Description", "Category"],
                                            order=[("Date", "desc")], limit=10)
    assert total == 1 and rows[0]["_id"] == "a"
    rows, total = transactions.search("", ["Description"], limit=2)
    assert total == 3 and len(rows) == 2
    rows, total = transactions.search("100%", ["Description"])
    assert total == 0, "LIKE wildcards in the query are escaped"


def test_budget_lines_cascade_on_budget_delete(store_db):
    budgets.insert({"_id": "bud_1", "budgetId": "B1", "versionName": "Baseline", "month": "2026-06"})
    budget_lines.insert_many([
        {"budget": "bud_1", "position": 0, "group": "Food", "amount": 400, "source": "historical", "dataPoints": 6},
        {"budget": "bud_1", "position": 1, "group": "Fun", "amount": 100, "source": "manual", "dataPoints": 0},
    ])
    assert budget_lines.count({"budget": "bud_1"}) == 2
    budgets.delete("bud_1")
    assert budget_lines.count({"budget": "bud_1"}) == 0


def test_where_rejects_unknown_key(store_db):
    with pytest.raises(KeyError):
        transactions.list({"Nope": 1})
