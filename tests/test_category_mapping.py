"""CategoryMapping — the deep module behind the savings and tax category→role mappings.
Tests the shared dance once (roster, seed-on-sync, skip-existing, role upsert + extras) over
the real mapping stores; the per-feature reductions live in test_savings.py / test_tax.py."""

import pytest

from app.category_mapping import CategoryMapping
from app.store.savings_category_mapping import savings_category_mapping
from app.store.tax_category_mapping import tax_category_mapping
from app.store.transactions import transactions
from app.web import DomainError
from tests import dbhelper


def _savings_seed(category, group, is_income):
    if category == "Savings":
        return "SAVINGS"
    return "INCOME" if is_income else "IGNORE"


def _mapping():
    return CategoryMapping(
        store=savings_category_mapping, role_field="Savings_Role",
        roles=("SAVINGS", "INCOME", "IGNORE"),
        seed=_savings_seed, new_extra={"Notes": "auto-synced — review role"})


def _seed_typed_ledger():
    """Replace the base ledger with a deterministic set carrying explicit Type (the seed
    signal the base transactions don't set)."""
    transactions.delete_where()
    dbhelper.seed(transactions, [
        {"_id": "x1", "Category": "Food", "Group": "Variable", "Type": "Expense", "Amount": -4.5},
        {"_id": "x2", "Category": "Salary", "Group": "Income", "Type": "Income", "Amount": 2000.0},
        {"_id": "x3", "Category": "Housing", "Group": "Fixed", "Type": "Expense", "Amount": -1500.0},
        {"_id": "x4", "Category": "Savings", "Group": "Savings", "Type": "Transfer", "Amount": -200.0},
    ])


def test_roster_is_distinct_categories_with_income_flag(store_db):
    _seed_typed_ledger()
    roster = dict((cat, is_income) for cat, _grp, is_income in _mapping().roster())
    assert roster == {"Food": False, "Salary": True, "Housing": False, "Savings": False}


def test_sync_seeds_roles_and_stamps_new_extra(store_db):
    _seed_typed_ledger()
    m = _mapping()
    res = m.sync()
    assert res == {"ok": True, "added": 4}
    docs = {d["_id"]: d for d in savings_category_mapping.list()}
    assert docs["Salary"]["Savings_Role"] == "INCOME"        # income-typed → INCOME
    assert docs["Food"]["Savings_Role"] == "IGNORE"          # plain spend → IGNORE
    assert docs["Savings"]["Savings_Role"] == "SAVINGS"      # seed override wins over Type
    assert docs["Food"]["Notes"] == "auto-synced — review role"
    assert docs["Food"]["Category"] == "Food" and docs["Food"]["Group"] == "Variable"
    assert [d["_id"] for d in m.docs()] == ["Food", "Housing", "Salary", "Savings"]


def test_sync_is_idempotent_and_keeps_existing_roles(store_db):
    _seed_typed_ledger()
    m = _mapping()
    m.sync()
    savings_category_mapping.update("Food", {"Savings_Role": "SAVINGS"})
    res = m.sync()                              # second run adds nothing
    assert res == {"ok": True, "added": 0}
    doc = savings_category_mapping.get("Food")
    assert doc["Savings_Role"] == "SAVINGS"                   # hand-set role untouched


def test_set_role_validates_against_allowed_roles(store_db):
    with pytest.raises(DomainError):
        _mapping().set_role({"category": "Food", "role": "BOGUS"})
    with pytest.raises(DomainError):
        _mapping().set_role({"role": "INCOME"})  # missing category


def test_set_role_required_rejects_empty_but_optional_allows_extras_only(store_db):
    m = _mapping()
    with pytest.raises(DomainError):                  # role_required default → empty role fails
        m.set_role({"category": "Food", "role": ""})

    extra = CategoryMapping(
        store=tax_category_mapping, role_field="tax_role",
        roles=("INCOME", "DEDUCTIBLE", "IGNORE"), seed=_savings_seed, new_extra={})
    res = extra.set_role(
        {"category": "Charity", "schedule": "A"}, extra_fields=("schedule",), role_required=False)
    assert res == {"ok": True, "category": "Charity", "role": None}
    doc = tax_category_mapping.get("Charity")
    assert doc["schedule"] == "A" and doc["tax_role"] is None  # extra written, role untouched
    res = extra.set_role({"category": "Charity", "role": "deductible"}, role_required=False)
    assert res["role"] == "DEDUCTIBLE"
    doc = tax_category_mapping.get("Charity")
    assert doc["tax_role"] == "DEDUCTIBLE" and doc["schedule"] == "A"   # upsert keeps the extra
