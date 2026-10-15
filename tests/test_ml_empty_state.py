"""The ML model's empty state (#230): a fresh database has no model file, and the pages say
so instead of doing nothing — the model tab counts the categorized rows a retrain needs, the
Ledger's ML suggest button is disabled with the reason, the suggest panel says there is no
model; the first retrain switches everything on at the next page load."""

from app import ml_model
from app.store.transactions import transactions
from tests import dbhelper


def test_model_info_reports_the_empty_state(store_client):
    d = store_client.get("/api/ml/model").json()
    assert d["model"] is None and d["trained"] is False
    assert d["labelled_rows"] == 3 and d["min_train_rows"] == ml_model.MIN_TRAIN_ROWS   # the ledger seed's rows
    assert ml_model.is_trained() is False


def test_ledger_button_and_panel_say_no_model(store_client):
    html = store_client.get("/").text
    assert 'id="ml-suggest-btn" disabled' in html and "No model yet" in html and "mlReady: false" in html
    d = store_client.get("/api/transactions/t1/suggest").json()
    assert d["model"] is False and d["ml"] == []


def test_retrain_below_the_minimum_explains_the_shortfall(store_client):
    r = store_client.post("/api/ml/retrain", json={})
    assert r.status_code == 400 and "Not enough" in r.json()["error"] and r.json()["rows_found"] == 3
    assert store_client.get("/api/ml/model").json()["trained"] is False


def test_the_first_retrain_switches_everything_on(store_client):
    dbhelper.seed(transactions,
        [{"_id": f"c{i}", "Description": f"shell gasoline {i}", "Amount": -40.0, "Category": "Auto"} for i in range(6)] +
        [{"_id": f"f{i}", "Description": f"starbucks coffee {i}", "Amount": -5.0, "Category": "Food"} for i in range(6)])
    assert store_client.get("/api/ml/model").json()["labelled_rows"] == 15
    r = store_client.post("/api/ml/retrain", json={})
    assert r.status_code == 200 and r.json()["status"] == "success"
    d = store_client.get("/api/ml/model").json()
    assert d["trained"] is True and d["model"]["rows_trained"] >= 10
    html = store_client.get("/").text                                   # the next page load
    assert 'id="ml-suggest-btn" disabled' not in html and "mlReady: true" in html
    s = store_client.get("/api/transactions/t1/suggest").json()
    assert s["model"] is True
