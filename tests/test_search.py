"""app/search.py — the one matching rule (words ANDed, fields ORed, case-insensitive)."""

from app import search
from app.inventory_item import SEARCH_FIELDS

DRILL = {"Item_ID": "X1", "Item_Name": "Drill", "Brand": "Bosch", "Category": "Tools",
         "Link": "https://example.com/dp/B0DRILL", "Notes": None, "Qty": 2}


def test_tokens_lowercase_split_and_cap():
    assert search.tokens("") == [] and search.tokens(None) == []
    assert search.tokens("  A b\tC ") == ["a", "b", "c"]
    assert search.tokens("1 2 3 4 5 6 7 8") == ["1", "2", "3", "4", "5", "6"]


def test_every_word_must_match_some_field():
    assert search.matches(DRILL, "bosch drill", SEARCH_FIELDS)
    assert search.matches(DRILL, "DRILL tools", SEARCH_FIELDS)
    assert not search.matches(DRILL, "bosch pen", SEARCH_FIELDS)


def test_item_id_and_empty_query_and_none_values():
    assert search.matches(DRILL, "x1", SEARCH_FIELDS)
    assert search.matches(DRILL, "", SEARCH_FIELDS) and search.matches(DRILL, None, SEARCH_FIELDS)
    assert search.matches({"Item_Name": None}, "", SEARCH_FIELDS)
    assert not search.matches({"Item_Name": None}, "x", SEARCH_FIELDS)


def test_link_and_numbers_are_not_searched():
    assert "Link" not in SEARCH_FIELDS and "Qty" not in SEARCH_FIELDS
    assert not search.matches(DRILL, "b0drill", SEARCH_FIELDS)
    assert search.matches(DRILL, "b0drill", ["Link"])          # only when a caller lists it
