"""The starter taxonomy (app/starter.py, app/seeds/categories.json): a fresh database gets
it once, through `manage.py init_store`; a database with any category row is left alone;
the file is checked before a row is written."""

import json

import pytest
from django.core.management import call_command

from app import starter
from app.budgets import all_groups
from app.store.account_categories import account_categories
from app.store.categories import categories
from app.store.inventory_categories import inventory_categories
from tests import dbhelper


def test_the_seed_file_is_sound():
    rows = starter.load_starter_categories()
    assert 40 <= len(rows) <= 80
    assert {r["Type"] for r in rows} == {"Income", "Expense", "Transfer"}
    assert len({r["Category"] for r in rows}) == len(rows)
    assert all(set(starter.FIELDS) <= set(r) for r in rows)


def test_a_bad_file_is_refused_before_anything_is_written(tmp_path, monkeypatch, store_db):
    bad = tmp_path / "categories.json"
    bad.write_text(json.dumps({"categories": [{"Category": "X", "Group": "G", "Type": "Spend", "Budget": "Discretionary",
                                                "Cashflow Type": "Operating Activities", "Timing": "Monthly"}]}))
    monkeypatch.setattr(starter, "SEED_FILE", bad)
    with pytest.raises(ValueError, match="Type 'Spend'"):
        starter.seed_categories()
    assert categories.count() == 0


def test_init_store_seeds_a_fresh_database_once(store_db, capsys):
    assert categories.count() == 0
    call_command("init_store")
    out = capsys.readouterr().out
    assert "starter categories written" in out
    n = categories.count()
    assert n == len(starter.load_starter_categories())
    row = categories.get("Groceries")
    assert row["Group"] == "Food" and row["Type"] == "Expense" and row["Timing"] == "Weekly"
    assert "starter account categories written" in out and "starter inventory categories written" in out
    assert account_categories.count() == len(starter.load_starter_account_categories())
    assert inventory_categories.count() == len(starter.load_starter_inventory_categories())
    call_command("init_store")                                      # a second start writes nothing
    assert categories.count() == n and "written" not in capsys.readouterr().out


def test_the_account_and_inventory_seed_files_are_sound():
    acct = starter.load_starter_account_categories()
    assert 25 <= len(acct) <= 60 and {r["Type"] for r in acct} == {"Assets", "Liabilities", "Equity"}
    by = {r["Category"]: r for r in acct}
    # the Add-account presets land on rows that say the same thing
    from app.views.accounts import ACCOUNT_TYPES
    for cfg in ACCOUNT_TYPES.values():
        row = by[cfg["preset"]["Category"]]
        assert (row["Group"], row["Type"]) == (cfg["preset"]["Group"], cfg["preset"]["Type"])
    inv = starter.load_starter_inventory_categories()
    assert 20 <= len(inv) <= 50 and len({r["Category"] for r in inv}) == len(inv)
    assert all(set(starter.INVENTORY_FIELDS) <= set(r) for r in inv)


def test_each_table_is_seeded_on_its_own_emptiness(store_db):
    dbhelper.seed(categories, [{"_id": "Mine", "Category": "Mine", "Group": "G"}])
    counts = starter.seed_all()
    assert counts["categories"] == 0 and counts["account categories"] > 0 and counts["inventory categories"] > 0
    assert [c["Category"] for c in categories.list()] == ["Mine"]
    assert account_categories.get("Checking Account")["Type"] == "Assets"
    assert inventory_categories.get("Furniture")["Group"] == "Home"


def test_a_database_with_any_category_is_left_alone(store_db, caplog):
    dbhelper.seed(categories, [{"_id": "Mine", "Category": "Mine", "Group": "G"}])
    assert starter.seed_categories() == 0
    assert [c["Category"] for c in categories.list()] == ["Mine"]
    assert any("not written" in r.getMessage() for r in caplog.records)


def test_the_seeded_rows_reach_the_pages(store_db, settings):
    from tests.client import WebClient
    settings.MONEY_AUTH_GATE = False
    starter.seed_categories()
    c = WebClient()
    starter.seed_account_categories(); starter.seed_inventory_categories()
    assert "Current Assets" in c.get("/api/categories/balances/sections").json()["sections"]
    assert "Kitchen" in c.get("/api/categories/inventory/sections").json()["sections"]
    sections = c.get("/api/categories/ledger/sections").json()["sections"]
    assert "Food" in sections and "Income" in sections and "Transfer" in sections
    items = c.get("/api/categories/ledger", params={"section": "Food"}).json()["items"]
    assert {i["Category"] for i in items} >= {"Groceries", "Restaurants", "Coffee"}
    ledger = c.get("/").text
    assert '"Category": "Groceries"' in ledger and '"Group": "Food"' in ledger       # the dropdown's list
    assert "Food" in all_groups() and "Savings" in all_groups()                        # the budget editor's picker
    assert c.get("/categories").status_code == 200
