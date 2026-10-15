"""Where the Rule engine and the ML model meet the Ledger (app/categorization.py +
app/views/categorization.py): the read-only suggest, Rule apply, ML suggest, retrain on
the new router, and the Ledger's split toolbar. The ML model is monkeypatched through the
module attribute the way production calls it."""

from app import categorization, ml_model
from app.store.autocat import autocat as autocat_store
from app.store.transactions import transactions
from tests import dbhelper


def _rule_and_blank_rows():
    dbhelper.seed(autocat_store, [
        {"_id": "r1", "Category": "Food", "Description Contains": "coffee", "order": 1}])
    dbhelper.seed(transactions, [
        {"_id": "b1", "Description": "Coffee Hut", "Amount": -4.0, "Category": ""},
        {"_id": "b2", "Description": "Mystery Shop", "Amount": -9.0},   # NULL Category
    ])


def _fake_predict(monkeypatch, preds):
    def fake(description, amount=0.0):
        return preds
    monkeypatch.setattr(ml_model, "predict", fake)
    assert categorization.ml_model is ml_model


# --- page + suggest -----------------------------------------------------------------

def test_page_renders(store_client):
    r = store_client.get("/categorization")
    assert r.status_code == 200 and "Categorization" in r.text


def test_suggest_returns_rule_and_ml_without_writing(store_client, monkeypatch):
    _rule_and_blank_rows()
    _fake_predict(monkeypatch, [{"category": "Snacks", "confidence": 0.91}])
    body = (store_client.get("/api/transactions/b1/suggest")).json()
    assert body["rule"] == {"id": "r1", "order": 1, "category": "Food",
                            "conditions": {"Description Contains": "coffee"}}
    assert body["ml"] == [{"category": "Snacks", "confidence": 0.91}]
    assert body["current"] == "" and body["stored"] == {"category": None, "confidence": None}
    assert (dbhelper.get(transactions, "b1"))["Category"] == ""      # nothing written


def test_suggest_shapes_without_rule_or_model_and_404(store_client):
    _rule_and_blank_rows()
    transactions.update("b2", {"Pred:Category": "Old", "Pred:Conf": 0.5})
    body = (store_client.get("/api/transactions/b2/suggest")).json()
    assert body == {"rule": None, "ml": [], "model": False, "current": None,
                    "stored": {"category": "Old", "confidence": 0.5}}
    assert (store_client.get("/api/transactions/nope/suggest")).status_code == 404


# --- Rule apply ------------------------------------------------------------------

def test_apply_rules_writes_only_rule_matches_with_cascade(store_client):
    _rule_and_blank_rows()
    r = store_client.post("/api/rules/apply", json={"scope": "blank"})
    assert r.json() == {"scanned": 2, "applied": 1, "unmatched": 1}
    b1 = dbhelper.get(transactions, "b1")
    assert b1["Category"] == "Food" and b1["Group"] == "Variable"        # cascade from the seed
    assert (dbhelper.get(transactions, "b2")).get("Category") is None
    assert (dbhelper.get(transactions, "t2"))["Category"] == "Income"   # seeded rows untouched
    # already-categorized rows are not rescanned
    assert (store_client.post("/api/rules/apply", json={})).json() == {
        "scanned": 1, "applied": 0, "unmatched": 1}


def test_apply_rules_rejects_unknown_scope(store_client):
    r = store_client.post("/api/rules/apply", json={"scope": "all"})
    assert r.status_code == 400 and r.json()["ok"] is False


# --- ML suggest ------------------------------------------------------------------

def test_suggest_batch_stores_predictions_never_category(store_client, monkeypatch):
    _rule_and_blank_rows()
    _fake_predict(monkeypatch, [{"category": "Snacks", "confidence": 0.91}])
    r = store_client.post("/api/ml/suggest-batch", json={})
    assert r.json() == {"scanned": 2, "suggested": 2, "no_suggestion": 0}
    for _id in ("b1", "b2"):
        row = dbhelper.get(transactions, _id)
        assert row.get("Category") in (None, "")                     # ML never writes Category
        assert row["Pred:Category"] == "Snacks" and row["Pred:Conf"] == 0.91


def test_suggest_batch_without_model_counts_only(store_client):
    _rule_and_blank_rows()
    r = store_client.post("/api/ml/suggest-batch", json={})
    assert r.json() == {"scanned": 2, "suggested": 0, "no_suggestion": 2}
    assert (dbhelper.get(transactions, "b1")).get("Pred:Category") is None


# --- moved / removed endpoints ----------------------------------------------------

def test_old_autocat_batch_is_gone_and_retrain_moved(store_client):
    assert (store_client.post("/api/transactions/autocat-batch")).status_code == 404
    r = store_client.post("/api/ml/retrain", json={})
    assert r.status_code == 400 and "Not enough" in r.json()["error"]   # answers on the new router


def test_import_graph_stays_acyclic():
    import app.views.ledger as ledger
    assert not hasattr(ledger, "autocat") and not hasattr(ledger, "ml_model")
    assert ledger.apply_category is categorization.apply_category
