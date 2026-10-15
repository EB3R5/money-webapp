"""AutoCat — the Rule engine, the deterministic, rules-first half of transaction
categorization.

A flat table of substring/amount-range Rules, applied first-match-wins (the model carried
over from the household's earlier spreadsheet tooling). The Rule rows live in the
`autocat` table, read through its Store. A Rule matches when EVERY non-empty condition it
declares holds against the transaction:

    Description Contains   — case-insensitive substring of the txn Description
    Account Contains       — case-insensitive substring of the txn Account
    Institution Contains   — case-insensitive substring of the txn Institution
    Amount Min / Amount Max — inclusive bounds on the (signed) txn Amount

A Rule is **active** when it is enabled, names a Category, and declares at least one
condition; a blank row can never swallow everything, and a disabled Rule never fires.
Rules fire in their explicit `order` (1-based, contiguous). Rows that predate the column
are numbered once, lazily, from their insertion order (`ensure_order`), so first-match-wins
keeps the order the rows were entered in.
"""

from typing import Optional

from .store.autocat import autocat as autocat_store

CONTAINS_FIELDS = (
    ("desc", "Description Contains", "Description"),
    ("acct", "Account Contains", "Account"),
    ("inst", "Institution Contains", "Institution"),
)

# The five condition columns, in the order the editor shows them.
RULE_FIELDS = ("Description Contains", "Account Contains", "Institution Contains",
               "Amount Min", "Amount Max")


def _text(v) -> Optional[str]:
    """Trimmed lowercase string, or None for blank/whitespace-only/None."""
    if v is None:
        return None
    s = str(v).strip().lower()
    return s or None


def _num(v) -> Optional[float]:
    """Parse an amount bound to float; None when blank/unparseable."""
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def is_enabled(raw: dict) -> bool:
    """A Rule's enabled flag; a row that predates the column reads as enabled."""
    v = raw.get("enabled")
    return True if v is None else bool(v)


def _compile_any(raw: dict) -> Optional[dict]:
    """Normalize one stored Rule regardless of its enabled flag. Returns None if it
    declares no usable condition or no Category. Carries the row's id and order so a
    caller can say which Rule fired."""
    rule = {
        "_id": raw.get("_id"),
        "order": raw.get("order"),
        "enabled": is_enabled(raw),
        "category": (raw.get("Category") or "").strip(),
        "desc": _text(raw.get("Description Contains")),
        "acct": _text(raw.get("Account Contains")),
        "inst": _text(raw.get("Institution Contains")),
        "amin": _num(raw.get("Amount Min")),
        "amax": _num(raw.get("Amount Max")),
    }
    has_cond = any(rule[k] for k in ("desc", "acct", "inst")) or \
        rule["amin"] is not None or rule["amax"] is not None
    if not has_cond or not rule["category"]:
        return None
    return rule


def _compile(raw: dict) -> Optional[dict]:
    """Normalize one stored Rule for the engine: None when disabled or unusable."""
    if not is_enabled(raw):
        return None
    return _compile_any(raw)


def ensure_order() -> int:
    """Number the Rules that have no `order` yet, after the highest existing one, in
    insertion order. Idempotent: returns how many rows were numbered (0 when none)."""
    pending = autocat_store.unordered()
    if not pending:
        return 0
    start = (autocat_store.max_order() or 0) + 1
    for i, raw in enumerate(pending):
        autocat_store.update(raw["_id"], {"order": start + i})
    return len(pending)


def sorted_docs() -> list[dict]:
    """Every stored Rule (enabled or not) in first-match-wins order, numbering any
    row that still lacks an `order` first."""
    ensure_order()
    return autocat_store.in_order()


def load_rules() -> list[dict]:
    """The compiled, enabled Rules in `order` — what the engine matches against."""
    rules = []
    for raw in sorted_docs():
        compiled = _compile(raw)
        if compiled:
            rules.append(compiled)
    return rules


def _txn_fields(txn: dict) -> tuple[dict, Optional[float]]:
    fields = {key: _text(txn.get(col)) for key, _hdr, col in CONTAINS_FIELDS}
    amount = txn.get("Amount")
    amount = float(amount) if isinstance(amount, (int, float)) else None
    return fields, amount


def _matches(rule: dict, fields: dict, amount: Optional[float]) -> bool:
    if any(rule[key] and (fields[key] is None or rule[key] not in fields[key])
           for key in ("desc", "acct", "inst")):
        return False
    if rule["amin"] is not None and (amount is None or amount < rule["amin"]):
        return False
    if rule["amax"] is not None and (amount is None or amount > rule["amax"]):
        return False
    return True


def match(txn: dict, rules: list[dict]) -> Optional[dict]:
    """First rule whose every declared condition holds for `txn`, else None."""
    fields, amount = _txn_fields(txn)
    for rule in rules:
        if _matches(rule, fields, amount):
            return rule
    return None


# --- Rule operations: the editor behind the Categorization page's Rules tab -----------
# Plain functions over the autocat store (no Request/Response), so they are
# unit-testable the way the lookups and registry operations are. Every write validates
# through _clean and reports a 4xx as a DomainError.

from .store.categories import categories as _categories  # noqa: E402
from .store.transactions import transactions as _transactions  # noqa: E402
from .store.deletions import deletions as _deletions  # noqa: E402
from .web import DomainError  # noqa: E402

EDITABLE = RULE_FIELDS + ("Category", "enabled")
AMOUNT_FIELDS = ("Amount Min", "Amount Max")


def known_categories() -> set[str]:
    return {c for c in _categories.distinct("Category") if c}


def issues(raw: dict, known: set[str]) -> list[str]:
    """Why a Rule is inactive (or merely suspect): disabled, no conditions, no Category,
    unknown Category. Only the last is a warning — the engine still fires on it."""
    out = []
    if not is_enabled(raw):
        out.append("disabled")
    probe = _compile_any({**raw, "Category": raw.get("Category") or "x"})
    if probe is None:
        out.append("no conditions")
    if not (raw.get("Category") or "").strip():
        out.append("no Category")
    elif raw["Category"].strip() not in known:
        out.append("unknown Category")
    return out


def _iso(v):
    """Timestamps go over the wire as ISO strings (the JSON guard has no datetime encoder)."""
    return v.isoformat() if hasattr(v, "isoformat") else v


def serialize(raw: dict, known: set[str]) -> dict:
    flags = issues(raw, known)
    return {
        "_id": raw.get("_id"), "id": raw.get("_id"),
        "order": raw.get("order"), "enabled": is_enabled(raw),
        "Category": raw.get("Category"),
        **{f: raw.get(f) for f in RULE_FIELDS},
        "_created_at": _iso(raw.get("_created_at")), "_edited_at": _iso(raw.get("_edited_at")),
        "active": is_enabled(raw) and _compile_any(raw) is not None,
        "issues": flags,
    }


def list_rules() -> dict:
    known = known_categories()
    return {"rules": [serialize(r, known) for r in sorted_docs()]}


def _clean(field: str, value, current: dict, known: set[str]):
    """Validate one editable field against the Rule as it would be after the edit."""
    if field not in EDITABLE:
        raise DomainError(f"unknown field '{field}'")
    if field == "enabled":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if field == "Category":
        v = (value or "").strip() if isinstance(value, str) else value
        if not v:
            raise DomainError("Category is required")
        if v not in known:
            raise DomainError(f"unknown Category '{v}'")
        return v
    if field in AMOUNT_FIELDS:
        if value is None or str(value).strip() == "":
            v = None
        else:
            v = _num(value)
            if v is None:
                raise DomainError(f"{field} not a number")
        merged = {**current, field: v}
        lo, hi = _num(merged.get("Amount Min")), _num(merged.get("Amount Max"))
        if lo is not None and hi is not None and lo > hi:
            raise DomainError("Amount Min must be ≤ Amount Max")
        return v
    # Contains fields: stripped text, blank → None.
    return (str(value).strip() or None) if value is not None else None


def add_rule(body: dict) -> dict:
    """Append a Rule (enabled, last in order). Body: Category + any of the conditions."""
    known = known_categories()
    doc: dict = {}
    doc["Category"] = _clean("Category", body.get("Category"), doc, known)
    for f in RULE_FIELDS:
        doc[f] = _clean(f, body.get(f), doc, known)
    doc["enabled"] = True
    doc["order"] = (autocat_store.max_order() or 0) + 1
    _id = autocat_store.insert(doc)
    return {"ok": True, "id": _id, "rule": serialize(autocat_store.get(_id), known)}


def update_rule(body: dict) -> dict:
    """Edit one field. Body: {id, field, value}; `field` may be `enabled`."""
    _id, field = body.get("id"), body.get("field")
    if not _id or not field:
        raise DomainError("bad id/field")
    current = autocat_store.get(_id)
    if current is None:
        raise DomainError("rule not found", 404)
    known = known_categories()
    value = _clean(field, body.get("value"), current, known)
    autocat_store.update(_id, {field: value})
    return {"ok": True, "rule": serialize(autocat_store.get(_id), known)}


def _renumber() -> None:
    """Make `order` contiguous from 1 in the current sequence."""
    for i, raw in enumerate(sorted_docs(), start=1):
        if raw.get("order") != i:
            autocat_store.update(raw["_id"], {"order": i})


def delete_rule(body: dict) -> dict:
    """Delete a Rule (audited to deletions), then renumber."""
    _id = body.get("id")
    if not _id:
        raise DomainError("no id")
    doc = autocat_store.get(_id)
    if doc is None:
        raise DomainError("rule not found", 404)
    _deletions.log("autocat", [doc])
    autocat_store.delete(_id)
    _renumber()
    return {"ok": True, "deleted": 1}


def move_rule(body: dict) -> dict:
    """Reorder: {id, direction: "up"|"down"} or {id, position: 1-based}. A move past a
    bound is a no-op that still succeeds. Returns the ids in their new order."""
    _id = body.get("id")
    ids = [r["_id"] for r in sorted_docs()]
    if _id not in ids:
        raise DomainError("rule not found", 404)
    i = ids.index(_id)
    if "position" in body:
        try:
            j = int(body["position"]) - 1
        except (TypeError, ValueError):
            raise DomainError("position not a number")
        j = max(0, min(j, len(ids) - 1))
    elif body.get("direction") == "up":
        j = max(0, i - 1)
    elif body.get("direction") == "down":
        j = min(len(ids) - 1, i + 1)
    else:
        raise DomainError("direction must be up or down, or give a position")
    if j != i:
        ids.insert(j, ids.pop(i))
        before = {r["_id"]: r.get("order") for r in autocat_store.in_order()}
        for n, rid in enumerate(ids, start=1):
            if before.get(rid) != n:
                autocat_store.update(rid, {"order": n})
    return {"ok": True, "order": ids}


# --- preview + test: what the Rules would do -------------------------------------------

def _blank_category(txn: dict) -> bool:
    return not (txn.get("Category") or "").strip()


def _sample(txn: dict) -> dict:
    d = txn.get("Date")
    return {"_id": txn.get("_id"), "Date": d.isoformat()[:10] if hasattr(d, "isoformat") else d,
            "Description": txn.get("Description"), "Amount": txn.get("Amount"),
            "Account": txn.get("Account"), "Category": txn.get("Category")}


def preview(samples: int = 5) -> dict:
    """One in-process pass over every Transaction. Per Rule: `matches` (in isolation,
    disabled Rules included), `wins` (fires first among the enabled Rules), and
    `uncategorized_wins` (wins on blank-Category rows: what Rule apply would write), plus
    up to `samples` matching rows. Precedence is computed here, not in SQL, so it is the
    engine's own. Returns {scanned, blank_unmatched, rules: {id: stats}}."""
    samples = max(0, int(samples))
    docs = sorted_docs()
    compiled = [(raw["_id"], _compile_any(raw)) for raw in docs]
    stats = {rid: {"matches": 0, "wins": 0, "uncategorized_wins": 0, "samples": []}
             for rid, _ in compiled}
    enabled = [(rid, rule) for rid, rule in compiled if rule and rule["enabled"]]
    scanned = blank_unmatched = 0
    for txn in _transactions.for_matching():
        scanned += 1
        fields, amount = _txn_fields(txn)
        for rid, rule in compiled:
            if rule and _matches(rule, fields, amount):
                st = stats[rid]
                st["matches"] += 1
                if len(st["samples"]) < samples:
                    st["samples"].append(_sample(txn))
        blank = _blank_category(txn)
        for rid, rule in enabled:
            if _matches(rule, fields, amount):
                stats[rid]["wins"] += 1
                if blank:
                    stats[rid]["uncategorized_wins"] += 1
                break
        else:
            if blank:
                blank_unmatched += 1
    return {"scanned": scanned, "blank_unmatched": blank_unmatched, "rules": stats}


def test_rule(body: dict, rules: list[dict]) -> dict | None:
    """Pure: which of `rules` (compiled, in order) would fire for a hand-typed Transaction.
    Amount is parsed leniently so a pasted "$1,200" works. Returns
    {rule_id, order, category, conditions} or None."""
    txn = {"Description": body.get("Description"), "Account": body.get("Account"),
           "Institution": body.get("Institution"), "Amount": _num(body.get("Amount"))}
    hit = match(txn, rules)
    if hit is None:
        return None
    conditions = {k: v for k, v in (
        ("Description Contains", hit["desc"]), ("Account Contains", hit["acct"]),
        ("Institution Contains", hit["inst"]), ("Amount Min", hit["amin"]),
        ("Amount Max", hit["amax"])) if v is not None}
    return {"rule_id": hit["_id"], "order": hit["order"], "category": hit["category"],
            "conditions": conditions}
