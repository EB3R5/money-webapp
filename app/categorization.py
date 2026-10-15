"""Categorization — where the Rule engine and the ML model meet the Ledger.

The two engines are separate modules (app/autocat.py rules, app/ml_model.py sklearn) and
stay that way; this module owns the operations that touch Transactions on their behalf,
the way app/credit.py backs app/views/credit.py:

  - the Category write with its derived-field cascade (ADR-0006), shared by the inline
    grid edit, a clicked Rule chip, and a clicked ML suggestion;
  - **Rule apply**: writing each winning Rule's Category onto the blank-Category
    Transactions, in batch;
  - **ML suggestion**: storing the ML model's top pick as `Pred:Category` / `Pred:Conf` on
    blank rows — the ML model only ever proposes and never writes Category;
  - the read-only suggest-for-one-Transaction the Ledger's side panel shows, with the Rule
    hit and the ML picks labelled by source.

The ML model is always called through the module attribute (`ml_model.predict`) so tests
can monkeypatch it.
"""

from . import autocat, ml_model
from .lookups import DERIVED_FIELDS
from .store.categories import categories
from .store.transactions import transactions
from .web import DomainError


def derived_for(category: str) -> dict:
    """The derived fields a Category stamps onto a Transaction (ADR-0006); {} if unknown."""
    cat = categories.one({"Category": category})
    return {f: cat.get(f) for f in DERIVED_FIELDS} if cat else {}


def apply_category(_id, value: str) -> dict:
    """Write a Category onto a Transaction, cascading the derived fields looked up from
    the categories store. Returns {ok, matched, derived}."""
    derived = derived_for(value)
    ok = transactions.update(_id, {"Category": value, **derived})
    return {"ok": ok, "matched": 1 if ok else 0, "derived": derived}


def _rule_summary(rule: dict | None) -> dict | None:
    """The part of a compiled Rule the panel and the test form show."""
    if rule is None:
        return None
    conditions = {k: v for k, v in (
        ("Description Contains", rule["desc"]), ("Account Contains", rule["acct"]),
        ("Institution Contains", rule["inst"]), ("Amount Min", rule["amin"]),
        ("Amount Max", rule["amax"])) if v is not None}
    return {"id": rule["_id"], "order": rule["order"], "category": rule["category"],
            "conditions": conditions}


def apply_rules(scope: str = "blank", ids=None) -> dict:
    """Rule apply over the blank-Category Transactions (all of them, or just the given
    ids — what the feed passes for the rows it just inserted): the first active Rule that
    matches writes its Category plus derived fields. Returns {scanned, applied, unmatched}."""
    if scope != "blank":
        raise DomainError(f"unknown scope '{scope}' (only 'blank' is supported)")
    rules = autocat.load_rules()
    scanned = applied = 0
    rows = (transactions.blank_among(ids) if ids is not None else transactions.blank())
    for txn in rows:
        scanned += 1
        rule = autocat.match(txn, rules)
        if rule:
            apply_category(txn["_id"], rule["category"])
            applied += 1
    return {"scanned": scanned, "applied": applied, "unmatched": scanned - applied}


def suggest_batch(ids=None) -> dict:
    """Store the ML model's top pick as an ML suggestion (`Pred:Category` / `Pred:Conf`)
    on every blank-Category Transaction (or just the given ids). Never writes Category.
    Returns {scanned, suggested, no_suggestion}."""
    scanned = suggested = 0
    rows = (transactions.blank_among(ids) if ids is not None else transactions.blank())
    for txn in rows:
        scanned += 1
        preds = ml_model.predict(txn.get("Description"), txn.get("Amount"))
        if preds:
            top = preds[0]
            transactions.update(
                txn["_id"], {"Pred:Category": top["category"], "Pred:Conf": top["confidence"]})
            suggested += 1
    return {"scanned": scanned, "suggested": suggested, "no_suggestion": scanned - suggested}


def ml_ready() -> bool:
    """Whether a model exists — the Ledger page reads it here, never the ML module itself
    (the import graph stays acyclic: Ledger → categorization → engines)."""
    return ml_model.is_trained()


def suggest_for(txn_id: str) -> dict:
    """Read-only: the Rule that would fire and the ML picks for one Transaction, plus what
    it holds now. Writes nothing; the caller applies a pick with apply_category."""
    txn = transactions.get(txn_id)
    if txn is None:
        raise DomainError("not found", 404)
    rule = autocat.match(txn, autocat.load_rules())
    predictions = ml_model.predict(txn.get("Description"), txn.get("Amount"))
    return {
        "rule": _rule_summary(rule),
        "ml": predictions,
        "model": ml_model.is_trained(),
        "current": txn.get("Category"),
        "stored": {"category": txn.get("Pred:Category"), "confidence": txn.get("Pred:Conf")},
    }


def test_transaction(body: dict) -> dict:
    """The Rules tab's "Test a transaction": what the Rule engine and the ML model would
    each say for hand-typed fields. Writes nothing."""
    rule = autocat.test_rule(body, autocat.load_rules())
    ml = ml_model.predict(body.get("Description"), autocat._num(body.get("Amount")) or 0.0)
    return {"rule": rule, "ml": ml}
