"""The Rules editor behind the Categorization page's Rules tab: the operations in
app/autocat.py (list/add/update/delete/move with validation) called directly, then the
page and its endpoints. The engine's own semantics live in tests/test_autocat.py."""

import pytest

from app import autocat
from app.store.autocat import autocat as autocat_store
from app.store.deletions import deletions
from app.web import DomainError
from tests import dbhelper


def _three_rules():
    dbhelper.seed(autocat_store, [
        {"_id": "r1", "Category": "Food", "Description Contains": "coffee", "order": 1},
        {"_id": "r2", "Category": "Auto", "Description Contains": "shell", "order": 2},
        {"_id": "r3", "Category": "Food", "Account Contains": "visa", "order": 3},
    ])


# --- operations, called directly ------------------------------------------------

def test_add_requires_known_category_and_appends_enabled(store_client):
    _three_rules()
    with pytest.raises(DomainError):
        autocat.add_rule({"Category": "Nope", "Description Contains": "x"})
    with pytest.raises(DomainError):
        autocat.add_rule({"Description Contains": "x"})            # no Category
    out = autocat.add_rule({"Category": "Auto", "Description Contains": "  Shell  ", "Amount Max": "-5"})
    rule = out["rule"]
    assert out["ok"] and rule["_id"] == out["id"]
    assert rule["order"] == 4 and rule["enabled"] is True and rule["active"] is True
    assert rule["Description Contains"] == "Shell" and rule["Amount Max"] == -5.0
    assert rule["_created_at"] is not None and rule["issues"] == []


def test_rule_without_conditions_saves_but_is_inactive(store_client):
    out = autocat.add_rule({"Category": "Food"})
    assert out["rule"]["active"] is False and out["rule"]["issues"] == ["no conditions"]
    assert autocat.load_rules() == []                                # the engine skips it


def test_amount_validation_and_clearing(store_client):
    _three_rules()
    with pytest.raises(DomainError):
        autocat.update_rule({"id": "r1", "field": "Amount Min", "value": "abc"})
    autocat.update_rule({"id": "r1", "field": "Amount Min", "value": "-20"})
    with pytest.raises(DomainError):                                        # min > max after merge
        autocat.update_rule({"id": "r1", "field": "Amount Max", "value": "-30"})
    out = autocat.update_rule({"id": "r1", "field": "Amount Max", "value": "-10"})
    assert out["rule"]["Amount Min"] == -20.0 and out["rule"]["Amount Max"] == -10.0
    out = autocat.update_rule({"id": "r1", "field": "Amount Min", "value": ""})
    assert out["rule"]["Amount Min"] is None                                 # blank clears
    with pytest.raises(DomainError):
        autocat.update_rule({"id": "r1", "field": "Bogus", "value": 1})


def test_enabled_toggle_excludes_from_engine(store_client):
    _three_rules()
    out = autocat.update_rule({"id": "r1", "field": "enabled", "value": "false"})
    assert out["rule"]["enabled"] is False and out["rule"]["active"] is False
    assert out["rule"]["issues"] == ["disabled"]
    assert [r["_id"] for r in autocat.load_rules()] == ["r2", "r3"]
    out = autocat.update_rule({"id": "r1", "field": "enabled", "value": True})
    assert out["rule"]["active"] is True


def test_unknown_category_is_a_warning_only(store_client):
    dbhelper.seed(autocat_store, [{"_id": "u", "Category": "Retired", "Description Contains": "x"}])
    rules = (autocat.list_rules())["rules"]
    assert rules[0]["issues"] == ["unknown Category"] and rules[0]["active"] is True
    assert (autocat.load_rules())[0]["category"] == "Retired"       # engine still fires
    with pytest.raises(DomainError):                                        # but you can't set one now
        autocat.update_rule({"id": "u", "field": "Category", "value": "Retired"})


def test_unknown_id_is_404(store_client):
    for op, body in ((autocat.update_rule, {"id": "nope", "field": "enabled", "value": True}),
                     (autocat.delete_rule, {"id": "nope"}),
                     (autocat.move_rule, {"id": "nope", "direction": "up"})):
        with pytest.raises(DomainError) as exc:
            op(body)
        assert exc.value.status == 404


def test_delete_audits_and_renumbers(store_client):
    _three_rules()
    assert autocat.delete_rule({"id": "r2"}) == {"ok": True, "deleted": 1}
    audit = dbhelper.one(deletions, collection="autocat")
    assert audit["doc"]["_id"] == "r2" and audit["doc"]["Description Contains"] == "shell"
    assert [(r["_id"], r["order"]) for r in autocat_store.in_order()] == [("r1", 1), ("r3", 2)]


def test_move_up_down_position_and_bounds(store_client):
    _three_rules()
    assert (autocat.move_rule({"id": "r3", "direction": "up"}))["order"] == ["r1", "r3", "r2"]
    assert (autocat.move_rule({"id": "r1", "direction": "up"}))["order"] == ["r1", "r3", "r2"]   # bound no-op
    assert (autocat.move_rule({"id": "r1", "direction": "down"}))["order"] == ["r3", "r1", "r2"]
    assert (autocat.move_rule({"id": "r2", "position": 1}))["order"] == ["r2", "r3", "r1"]
    assert (autocat.move_rule({"id": "r2", "position": 99}))["order"] == ["r3", "r1", "r2"]
    assert [(r["_id"], r["order"]) for r in autocat_store.in_order()] == [("r3", 1), ("r1", 2), ("r2", 3)]
    with pytest.raises(DomainError):
        autocat.move_rule({"id": "r2", "direction": "sideways"})


# --- page + endpoints -------------------------------------------------------------

def test_page_nav_and_ledger_link(store_client):
    r = store_client.get("/categorization")
    assert r.status_code == 200
    assert 'id="tab-rules"' in r.text and 'id="add-rule"' in r.text and "categorization.js" in r.text
    assert '"Auto", "Food"' in r.text                                     # known categories for the editor
    assert 'href="/categorization">Categorization</a>' in r.text          # nav link (base.html)
    assert 'href="/categorization"' in (store_client.get("/")).text  # Ledger "Manage rules"


def test_endpoints_list_add_update_move_delete(store_client):
    _three_rules()
    rules = (store_client.get("/api/rules")).json()["rules"]
    assert [r["order"] for r in rules] == [1, 2, 3] and rules[0]["active"] is True

    r = store_client.post("/api/rules/row", json={"Category": "Auto", "Description Contains": "gas"})
    assert r.json()["ok"] and r.json()["rule"]["order"] == 4
    new_id = r.json()["id"]
    assert (store_client.post("/api/rules/row", json={"Category": "Nope"})).status_code == 400

    r = store_client.post("/api/rules/update", json={"id": "r1", "field": "Account Contains", "value": " Chase "})
    assert r.json()["rule"]["Account Contains"] == "Chase"
    assert (store_client.post("/api/rules/update", json={"id": "zz", "field": "enabled", "value": 1})).status_code == 404

    r = store_client.post("/api/rules/move", json={"id": "r3", "position": 1})
    assert r.json()["order"][0] == "r3"

    r = store_client.post("/api/rules/delete", json={"id": "r1"})
    assert r.json() == {"ok": True, "deleted": 1}
    remaining = (store_client.get("/api/rules")).json()["rules"]
    assert [(x["_id"], x["order"]) for x in remaining] == [("r3", 1), ("r2", 2), (new_id, 3)]


def test_data_health_has_rules_section(store_client):
    from app import data_health as H
    assert any(s["key"] == "autocat" and s["collection"] == "autocat" for s in H.SECTIONS)
    snap = H.compute_health()
    assert "autocat" in {s["key"] for s in snap["sections"]}


# --- preview + test form ----------------------------------------------------------

def test_preview_matches_vs_wins_vs_uncategorized_with_samples_cap(store_client):
    from app.store.transactions import transactions
    dbhelper.seed(autocat_store, [
        {"_id": "off", "Category": "Food", "Description Contains": "coffee", "order": 1, "enabled": False},
        {"_id": "wide", "Category": "Auto", "Description Contains": "co", "order": 2},
        {"_id": "narrow", "Category": "Food", "Description Contains": "coffee", "order": 3},
    ])
    dbhelper.seed(transactions, [
        {"_id": f"c{i}", "Description": f"Coffee {i}", "Amount": -4.0} for i in range(7)])
    d = (store_client.get("/api/rules/preview?samples=3")).json()
    # the seed has 3 categorized rows (Coffee/Paycheck/Rent) + 7 blank "Coffee n" rows
    assert d["scanned"] == 10 and d["blank_unmatched"] == 0
    off, wide, narrow = d["rules"]["off"], d["rules"]["wide"], d["rules"]["narrow"]
    assert off["matches"] == 8 and off["wins"] == 0 and off["uncategorized_wins"] == 0   # disabled: matches, never wins
    assert wide["matches"] == 8 and wide["wins"] == 8 and wide["uncategorized_wins"] == 7
    assert narrow["matches"] == 8 and narrow["wins"] == 0                                # shadowed by "wide"
    assert len(wide["samples"]) == 3 and len(off["samples"]) == 3
    assert {"_id", "Date", "Description", "Amount", "Account", "Category"} == set(wide["samples"][0])
    assert (store_client.get("/api/rules/preview?samples=0")).json()["rules"]["wide"]["samples"] == []


def test_preview_counts_unmatched_blank_rows(store_client):
    from app.store.transactions import transactions
    dbhelper.seed(autocat_store, [{"_id": "r", "Category": "Food", "Description Contains": "zzz"}])
    dbhelper.seed(transactions, [{"_id": "b", "Description": "Mystery", "Amount": -1.0}])
    d = (store_client.get("/api/rules/preview")).json()
    assert d["blank_unmatched"] == 1 and d["rules"]["r"]["matches"] == 0


def test_test_form_parses_string_amounts_and_inserts_nothing(store_client, monkeypatch):
    from app import ml_model
    from app.store.transactions import transactions
    dbhelper.seed(autocat_store, [
        {"_id": "r1", "Category": "Auto", "Description Contains": "shell", "Amount Max": -20, "order": 1}])
    seen = {}

    def fake_predict(description, amount=0.0):
        seen["args"] = (description, amount)
        return [{"category": "Auto", "confidence": 0.8}]
    monkeypatch.setattr(ml_model, "predict", fake_predict)

    before = transactions.count()
    r = store_client.post("/api/rules/test", json={"Description": "Shell Oil", "Amount": "$-45.10"})
    assert r.json() == {"rule": {"rule_id": "r1", "order": 1, "category": "Auto",
                                 "conditions": {"Description Contains": "shell", "Amount Max": -20.0}},
                        "ml": [{"category": "Auto", "confidence": 0.8}]}
    assert seen["args"] == ("Shell Oil", -45.1)
    r = store_client.post("/api/rules/test", json={"Description": "Shell Oil", "Amount": "-5"})
    assert r.json()["rule"] is None                                        # above the max
    assert transactions.count() == before                            # nothing written
    assert autocat.test_rule({"Description": "x"}, []) is None


def test_page_has_preview_button_and_test_form(store_client):
    html = (store_client.get("/categorization")).text
    for el in ('id="preview-btn"', 'id="rule-test-form"', 'id="rule-test-rule"', 'id="rule-test-ml"', 'id="rule-samples"'):
        assert el in html
