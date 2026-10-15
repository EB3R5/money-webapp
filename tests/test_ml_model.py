"""Local ML categorization (app/ml_model.py) on the store layer: the model file lives under
the test's Data directory and its pointer row in model_versions, so store/load round-trips
run for real. predict tests inject a really trained pipeline; the training frame, the
too-few-rows guards, and the canonical-category filter run against the seeded stores."""

import io
from datetime import datetime

import joblib
import pandas as pd
import pytest

from app import ml_model
from app.store import database
from app.store.model_versions import model_versions
from app.store.transactions import transactions
from tests import dbhelper


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    """Never reuse a pipeline cached by another test (or by the real app)."""
    monkeypatch.setattr(ml_model, "_pipeline", None)
    monkeypatch.setattr(ml_model, "_cached_key", None)


def _tiny_pipeline():
    """A genuinely fitted pipeline over two obvious categories."""
    X = pd.DataFrame({
        "text": ["starbucks coffee", "coffee shop latte", "coffee beans",
                 "shell gasoline", "gas station fuel", "fuel pump diesel"],
        "amount": [-5.0, -6.0, -12.0, -40.0, -35.0, -50.0],
    })
    y = ["Coffee", "Coffee", "Coffee", "Gas", "Gas", "Gas"]
    pipeline = ml_model.build_pipeline()
    pipeline.fit(X, y)
    return pipeline


def _pickle(pipeline) -> bytes:
    buf = io.BytesIO()
    joblib.dump(pipeline, buf)
    return buf.getvalue()


# --- storage -------------------------------------------------------------------

def test_store_model_writes_file_and_pointer_row_then_loads_back(store_db):
    doc = ml_model.store_model(_pickle(_tiny_pipeline()), {"rows_trained": 6})
    row = model_versions.one({"name": ml_model.ML_MODEL_NAME})
    assert row["_id"] == ml_model.ML_MODEL_NAME and row["path"] == doc["path"]
    assert row["path"].startswith("models/") and (store_db / row["path"]).exists()
    assert row["sha256"] == doc["sha256"] and row["rows_trained"] == 6

    pipeline = ml_model.get_model()
    assert pipeline is not None and set(pipeline.classes_) == {"Coffee", "Gas"}
    assert ml_model.get_model() is pipeline              # cached


def test_store_model_replaces_prior_file_and_invalidates_cache(store_db):
    first = ml_model.store_model(b"not really a model", {})
    assert (store_db / first["path"]).exists()
    with pytest.raises(Exception):
        ml_model.get_model()                            # unpicklable bytes

    second = ml_model.store_model(_pickle(_tiny_pipeline()), {})
    assert second["_id"] == first["_id"]                      # one pointer row, updated
    assert not (store_db / first["path"]).exists()            # superseded file dropped
    assert model_versions.count() == 1
    assert (ml_model.get_model()) is not None


def test_get_model_rejects_tampered_file(store_db):
    doc = ml_model.store_model(_pickle(_tiny_pipeline()), {})
    (database.data_dir / doc["path"]).write_bytes(b"tampered")
    with pytest.raises(RuntimeError):
        ml_model.get_model()


# --- predict -------------------------------------------------------------------

def test_predict_ranks_the_right_category_first(store_db, monkeypatch):
    pipeline = _tiny_pipeline()

    def fake_get_model():
        return pipeline
    monkeypatch.setattr(ml_model, "get_model", fake_get_model)
    monkeypatch.setattr(ml_model, "ML_CONF_MIN", 0.0)

    preds = ml_model.predict("starbucks coffee downtown", -5.5)
    assert preds and preds[0]["category"] == "Coffee"
    assert all(0.0 <= p["confidence"] <= 1.0 for p in preds)
    assert preds == sorted(preds, key=lambda p: -p["confidence"])

    monkeypatch.setattr(ml_model, "ML_CONF_MIN", 1.1)          # threshold filters everything
    assert ml_model.predict("starbucks coffee downtown", -5.5) == []


def test_predict_empty_without_text_or_model(store_db):
    assert ml_model.predict("   ") == []                 # blank text: model never loaded
    # No model_versions row → get_model None → no predictions.
    assert ml_model.predict("starbucks", -5.0) == []


# --- training frame --------------------------------------------------------------

def test_training_frame_filters_and_text_fallback(store_db):
    dbhelper.seed(transactions, [
        {"_id": "m1", "Date": datetime(2026, 1, 5), "Account": "Chase",
         "Description": "short", "Full Description": "FULL TEXT WINS",
         "Amount": -5.0, "Category": "Coffee"},
        {"_id": "m2", "Date": datetime(2026, 2, 5), "Account": "Ally",
         "Description": "other account", "Amount": -9.0, "Category": "Gas"},
        {"_id": "m3", "Date": datetime(2026, 1, 6), "Account": "Chase",
         "Description": "unlabelled", "Amount": -1.0, "Category": ""},
        {"_id": "m4", "Date": datetime(2026, 1, 31), "Account": "Chase",
         "Description": "on the end date", "Amount": -2.0, "Category": "Gas"},
    ])
    df = ml_model._training_frame(
        {"accounts": ["Chase"], "start_date": "2026-01-01", "end_date": "2026-01-31"})
    assert df["text"].tolist() == ["FULL TEXT WINS", "on the end date"]   # m2 account, m3 blank
    assert df["category"].tolist() == ["Coffee", "Gas"]


# --- retrain ---------------------------------------------------------------------

def test_retrain_needs_enough_labelled_rows(store_client):
    result = ml_model.retrain()
    assert "error" in result
    # the ledger seed has 3 labelled rows — still below MIN_TRAIN_ROWS.
    assert result["rows_found"] == 3


def test_retrain_rejects_rows_outside_canonical_categories(store_client):
    # 12 labelled rows, but every category is unknown to the categories store.
    dbhelper.seed(transactions, [
        {"_id": f"u{i}", "Description": f"txn {i}", "Amount": -1.0 * i,
         "Category": "NotACategory"} for i in range(12)])
    result = ml_model.retrain()
    assert "error" in result
    assert "NotACategory" in result["unknown_categories"]


def test_retrain_trains_and_stores_a_working_model(store_client):
    # 6 rows per canonical category (Auto/Food are in the ledger seed).
    dbhelper.seed(transactions,
        [{"_id": f"c{i}", "Description": f"shell gasoline {i}", "Amount": -40.0,
          "Category": "Auto"} for i in range(6)] +
        [{"_id": f"f{i}", "Description": f"starbucks coffee {i}", "Amount": -5.0,
          "Category": "Food"} for i in range(6)])

    r = store_client.post("/api/ml/retrain", json={})
    assert r.status_code == 200
    result = r.json()
    assert result["status"] == "success"
    # the seed has Food/Income/Housing txns; only Food is canonical → 12 new + 1 seeded.
    assert result["rows_trained"] == 13
    assert result["n_categories"] == 2
    assert result["unknown_categories"] == ["Housing", "Income"]

    row = model_versions.one({"name": ml_model.ML_MODEL_NAME})
    assert row["source"] == "sqlite:transactions" and row["rows_trained"] == 13
    pipeline = ml_model.get_model()
    X = pd.DataFrame({"text": ["shell gasoline fill up"], "amount": [-42.0]})
    assert pipeline.predict(X)[0] == "Auto"


# --- model info (the ML model tab) ---------------------------------------------

def test_model_info_without_and_with_a_model(store_db, monkeypatch):
    monkeypatch.setattr(ml_model, "ML_CONF_MIN", 0.42)
    info = ml_model.model_info()
    assert info == {"model": None, "trained": False, "labelled_rows": 0, "conf_min": 0.42,
                    "min_train_rows": ml_model.MIN_TRAIN_ROWS}

    doc = ml_model.store_model(_pickle(_tiny_pipeline()), {
        "trained_at": "2026-09-21T10:00:00+00:00", "rows_trained": 6, "n_categories": 2,
        "filters_applied": {"accounts": ["Visa"]}, "source": "test"})
    info = ml_model.model_info()
    m = info["model"]
    assert m["path"] == doc["path"] and m["sha256"] == doc["sha256"]
    assert m["rows_trained"] == 6 and m["n_categories"] == 2 and m["source"] == "test"
    assert m["filters_applied"] == {"accounts": ["Visa"]}
    assert isinstance(m["trained_at"], str) and m["trained_at"].startswith("2026-09-21")
    assert m["sklearn_version"]


def test_model_endpoint_and_tab(store_client, monkeypatch):
    monkeypatch.setattr(ml_model, "ML_CONF_MIN", 0.3)
    r = store_client.get("/api/ml/model")
    assert r.status_code == 200 and r.json()["model"] is None and r.json()["conf_min"] == 0.3
    html = (store_client.get("/categorization")).text
    for el in ('id="model-info"', 'id="retrain-form"', 'id="retrain-status"', 'id="conf-min"'):
        assert el in html
    assert ">0.3<" in html                                                  # the floor is rendered
