"""Categorization page + its endpoints: the Rules editor (app/autocat.py operations), the
places where the Rule engine and the ML model meet the Ledger (app/categorization.py),
and retrain. Thin adapter through the shared web.json()/web.read_json() seam; a
DomainError raised by an operation is its JSON 4xx (app.middleware)."""

from django.urls import path

from .. import autocat, categorization, ml_model, web


@web.GET
def categorization_page(request):
    return web.page(request, "categorization.html", {
        "categories": sorted(autocat.known_categories()),
        "rule_fields": list(autocat.RULE_FIELDS),
        "conf_min": ml_model.ML_CONF_MIN,     # the module global, same source as /api/ml/model
    })


# --- Rules editor ---------------------------------------------------------------

@web.GET
def list_rules(request):
    return web.json(autocat.list_rules())


@web.POST
def add_rule(request):
    return web.json(autocat.add_rule(web.read_json(request)))


@web.POST
def update_rule(request):
    return web.json(autocat.update_rule(web.read_json(request)))


@web.POST
def delete_rule(request):
    return web.json(autocat.delete_rule(web.read_json(request)))


@web.POST
def move_rule(request):
    return web.json(autocat.move_rule(web.read_json(request)))


@web.GET
def preview_rules(request):
    """Per-Rule match / win / uncategorized-win counts with sample rows, from one scan."""
    try:
        samples = int(request.GET.get("samples", 5))
    except ValueError:
        samples = 5
    return web.json(autocat.preview(samples))


@web.POST
def test_rule(request):
    """Body: {Description, Account, Institution, Amount} → {rule, ml}. Writes nothing."""
    return web.json(categorization.test_transaction(web.read_json(request)))


# --- where the engines meet the Ledger ----------------------------------------------

@web.POST
def apply_rules(request):
    """Rule apply over blank-Category Transactions. Body: {scope: "blank"}."""
    body = web.read_json(request)
    return web.json(categorization.apply_rules(body.get("scope", "blank")))


@web.POST
def suggest_batch(request):
    """Store the ML model's top pick as an ML suggestion on every blank row."""
    return web.json(categorization.suggest_batch())


@web.GET
def suggest(request, txn_id: str):
    """The Rule hit and the ML picks for one Transaction; writes nothing. 404 if unknown."""
    return web.json(categorization.suggest_for(txn_id))


@web.GET
def model_info(request):
    """The current model's pointer row, the confidence floor, the minimum training rows."""
    return web.json(ml_model.model_info())


@web.POST
def retrain_model(request):
    """Rebuild the ML model from the transactions store and replace the model file.
    Body (all optional): {start_date, end_date, accounts:[...]}."""
    filters = web.read_json(request)
    result = ml_model.retrain(filters or {})
    return web.json(result, 200 if result.get("status") == "success" else 400)


urlpatterns = [
    path("categorization", categorization_page),
    path("api/rules", list_rules),
    path("api/rules/row", add_rule),
    path("api/rules/update", update_rule),
    path("api/rules/delete", delete_rule),
    path("api/rules/move", move_rule),
    path("api/rules/preview", preview_rules),
    path("api/rules/test", test_rule),
    path("api/rules/apply", apply_rules),
    path("api/ml/suggest-batch", suggest_batch),
    path("api/transactions/<str:txn_id>/suggest", suggest),
    path("api/ml/model", model_info),
    path("api/ml/retrain", retrain_model),
]
