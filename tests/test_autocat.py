"""AutoCat — the Rule engine (app/autocat.py). Rule semantics under test: every declared
condition must hold, first active Rule in `order` wins, and a blank rule can never swallow
everything. The endpoints that drive it live in tests/test_categorization.py."""

from app import autocat
from app.store.autocat import autocat as autocat_store
from app.store.transactions import transactions
from tests import dbhelper


def _rule(**kw):
    """A stored-shape rule row; only the conditions passed are declared."""
    return {"Category": kw.pop("category", "Food"), **kw}


# --- match() / _compile() — pure, no DB --------------------------------------

def test_first_match_wins_in_order():
    rules = [autocat._compile(r) for r in (
        _rule(category="Coffee", **{"Description Contains": "starbucks"}),
        _rule(category="Food", **{"Description Contains": "star"}),
    )]
    hit = autocat.match({"Description": "STARBUCKS STORE 5424"}, rules)
    assert hit["category"] == "Coffee"


def test_contains_is_case_insensitive_substring():
    rules = [autocat._compile(_rule(**{"Account Contains": "checking"}))]
    assert autocat.match({"Account": "MAIN CHECKING"}, rules)
    assert autocat.match({"Account": "Savings"}, rules) is None
    assert autocat.match({}, rules) is None                    # missing field can't match


def test_every_declared_condition_must_hold():
    rules = [autocat._compile(_rule(
        **{"Description Contains": "amazon", "Amount Min": -50, "Amount Max": 0}))]
    assert autocat.match({"Description": "Amazon Mktpl", "Amount": -38.6}, rules)
    assert autocat.match({"Description": "Amazon Mktpl", "Amount": -80.0}, rules) is None
    assert autocat.match({"Description": "Target", "Amount": -38.6}, rules) is None


def test_amount_bounds_are_inclusive_and_need_an_amount():
    rules = [autocat._compile(_rule(**{"Amount Min": "-20", "Amount Max": "-10"}))]
    assert autocat.match({"Amount": -20.0}, rules)
    assert autocat.match({"Amount": -10.0}, rules)
    assert autocat.match({"Amount": -9.99}, rules) is None
    assert autocat.match({"Amount": None}, rules) is None      # bounded rule needs an amount


def test_blank_or_categoryless_rules_compile_to_none():
    assert autocat._compile({"Category": "Food"}) is None              # no conditions
    assert autocat._compile(_rule(category="", **{"Description Contains": "x"})) is None
    assert autocat._compile({"Category": "Food", "Description Contains": "  "}) is None


def test_num_parses_money_strings():
    assert autocat._num("$1,200.50") == 1200.5
    assert autocat._num("") is None
    assert autocat._num("abc") is None


# --- load_rules — store order, blank rows dropped -----------------------------

def test_load_rules_preserves_order_and_skips_blanks(store_db):
    dbhelper.seed(autocat_store, [
        {"_id": "r1", "Category": "Coffee", "Description Contains": "starbucks"},
        {"_id": "r2", "Category": "Ignored"},                  # no conditions → dropped
        {"_id": "r3", "Category": "Food", "Description Contains": "star", "Amount Min": -50},
    ])
    rules = autocat.load_rules()
    assert [r["category"] for r in rules] == ["Coffee", "Food"]
    assert rules[1]["amin"] == -50.0                           # REAL column parsed as a bound


# --- order + enabled ------------------------------------------------------------

def test_ensure_order_backfills_insertion_order_once(store_db):
    dbhelper.seed(autocat_store, [
        {"_id": "r1", "Category": "Coffee", "Description Contains": "starbucks"},
        {"_id": "r2", "Category": "Food", "Description Contains": "star"},
        {"_id": "r3", "Category": "Gas", "Description Contains": "shell"},
    ])
    assert autocat.ensure_order() == 3
    assert [(r["_id"], r["order"]) for r in autocat_store.in_order()] == [
        ("r1", 1), ("r2", 2), ("r3", 3)]
    assert autocat.ensure_order() == 0                      # idempotent
    # A row added later without an order lands after the highest existing one.
    dbhelper.seed(autocat_store, [{"_id": "r4", "Category": "X", "Description Contains": "x"}])
    assert autocat.ensure_order() == 1
    assert (autocat_store.get("r4"))["order"] == 4


def test_load_rules_sorts_by_order_not_insertion(store_db):
    dbhelper.seed(autocat_store, [
        {"_id": "late", "Category": "Food", "Description Contains": "star", "order": 2},
        {"_id": "first", "Category": "Coffee", "Description Contains": "starbucks", "order": 1},
    ])
    rules = autocat.load_rules()
    assert [r["_id"] for r in rules] == ["first", "late"]
    assert autocat.match({"Description": "STARBUCKS 5424"}, rules)["category"] == "Coffee"
    # Swap the order and the other Rule wins the same Transaction.
    autocat_store.update("late", {"order": 0})
    rules = autocat.load_rules()
    assert autocat.match({"Description": "STARBUCKS 5424"}, rules)["category"] == "Food"


def test_disabled_rule_never_fires(store_db):
    dbhelper.seed(autocat_store, [
        {"_id": "off", "Category": "Coffee", "Description Contains": "starbucks", "enabled": False},
        {"_id": "on", "Category": "Food", "Description Contains": "star", "enabled": True},
        {"_id": "legacy", "Category": "Gas", "Description Contains": "shell"},   # no flag → enabled
    ])
    rules = autocat.load_rules()
    assert [r["_id"] for r in rules] == ["on", "legacy"]
    assert autocat.match({"Description": "STARBUCKS"}, rules)["category"] == "Food"
    assert autocat._compile({"Category": "C", "Description Contains": "x", "enabled": False}) is None
    compiled = autocat._compile_any({"_id": "z", "order": 7, "Category": "C",
                                     "Description Contains": "x", "enabled": False})
    assert compiled["_id"] == "z" and compiled["order"] == 7 and compiled["enabled"] is False


def test_suggest_honours_order_and_enabled_end_to_end(store_client):
    dbhelper.seed(autocat_store, [
        {"_id": "a", "Category": "Auto", "Description Contains": "coffee", "order": 2},
        {"_id": "b", "Category": "Food", "Description Contains": "coffee", "order": 1, "enabled": False},
    ])
    dbhelper.seed(transactions, [{"_id": "s9", "Description": "Coffee Hut", "Amount": -4.0}])
    body = (store_client.get("/api/transactions/s9/suggest")).json()
    assert body["rule"]["category"] == "Auto" and body["rule"]["order"] == 2   # b is first but disabled
