"""Lookup-management factory — one deep module behind the /categories page.

A *lookup* table (e.g. `categories`, `account_categories`) is the single source of a
`Category → Group + derived-fields` mapping. Those derived fields are denormalized onto a
*target* table at write time (ADR-0006: transactions carry their category's Group/Budget/etc;
balance history carries its account-category's Group/Type). Editing the mapping must
therefore (a) update the lookup row and (b) *cascade* the change onto every target row that
referenced it — the ADR-0006 backfill.

This module owns that dance once, parameterized by a `LookupContext`. Each context declares
its lookup store, its section/item fields, which fields cascade, and the target store + match
field they flow into. The `categories` router is a thin adapter that picks a context by slug
and calls these functions; the ledger keeps its own bespoke per-transaction category endpoint
(it also feeds AutoCat/ML) and just imports the shared field list.

The operations are plain functions (no Request/Response), so they're unit-testable the
same way the Grid's are. A lookup row's id is the item value.
"""

from dataclasses import dataclass

from .store.account_categories import account_categories
from .store.balance_history import balance_history
from .store.base import Store
from .store.categories import categories
from .store.deletions import deletions
from .store.inventory import inventory
from .store.inventory_categories import inventory_categories
from .store.transactions import transactions
from .web import DomainError

# Lookup-CRUD errors are ordinary DomainErrors; alias keeps the raise sites reading naturally.
LookupError = DomainError


@dataclass(frozen=True)
class LookupContext:
    slug: str                      # url + registry key, e.g. "ledger"
    label: str                     # button text, e.g. "Ledger Categories"
    store: Store                   # lookup store (the table you edit)
    section_field: str             # hierarchy section you flip through, e.g. "Group"
    item_field: str                # the key item, e.g. "Category"
    cascade_fields: tuple          # fields pushed onto target rows when changed (incl. section)
    target: Store                  # where the derived fields are denormalized
    target_match_field: str        # target field whose value equals the item value
    item_noun: str = "item"        # singular noun for UI/messages
    target_noun: str = "row"       # singular noun for the cascade count message
    extra_fields: tuple = ()       # editable columns that never cascade (descriptive metadata)

    @property
    def collection(self) -> str:
        """The lookup table's name — the label the Categories page and the audit log use."""
        return self.store.table

    @property
    def columns(self) -> list:
        """Editable grid columns: the item, the section you organize by, the cascade fields,
        then any extra descriptive fields (item first, deduped). Section + extras are editable
        without cascading — for a context whose grouping/metadata don't flow onto the target
        (e.g. inventory's Group / Subcategory / Classification)."""
        cols = [self.item_field]
        for f in (self.section_field, *self.cascade_fields, *self.extra_fields):
            if f not in cols:
                cols.append(f)
        return cols


# --- the registry: add a context here and the /categories page grows a button -----
CONTEXTS = {
    "ledger": LookupContext(
        slug="ledger", label="Ledger Categories",
        store=categories, section_field="Group", item_field="Category",
        cascade_fields=("Group", "Budget", "Cashflow Type", "Timing", "Type"),
        target=transactions, target_match_field="Category",
        item_noun="category", target_noun="transaction",
    ),
    "balances": LookupContext(
        slug="balances", label="Balances",
        store=account_categories, section_field="Group", item_field="Category",
        # Type is the coarse kind the balance sheet reads; the granular Account Type is
        # not derived from the lookup (Balances port, schema 0006).
        cascade_fields=("Group", "Type"),
        target=balance_history, target_match_field="Category",
        item_noun="account category", target_noun="balance row",
    ),
    "inventory": LookupContext(
        slug="inventory", label="Inventory Categories",
        store=inventory_categories, section_field="Group", item_field="Category",
        # Rename re-points inventory items (always); Group is purely organizational
        # here — an empty cascade means editing it never stamps onto the items.
        cascade_fields=(),
        # Descriptive metadata backfilled from the items (see scripts/import_inventory_categories.py).
        extra_fields=("Subcategory", "Classification"),
        target=inventory, target_match_field="Category",
        item_noun="inventory category", target_noun="item",
    ),
}

# The ledger's per-transaction category cascade (ledger.py) shares this field list.
DERIVED_FIELDS = list(CONTEXTS["ledger"].cascade_fields)


def get_context(slug: str) -> LookupContext:
    ctx = CONTEXTS.get(slug)
    if ctx is None:
        raise LookupError(f"unknown context '{slug}'", status=404)
    return ctx


def _serialize(ctx: LookupContext, doc: dict) -> dict:
    out = {"_id": str(doc.get("_id"))}
    for c in ctx.columns:
        out[c] = doc.get(c)
    return out


# --- read -------------------------------------------------------------------

def list_sections(ctx: LookupContext) -> list:
    """Distinct, sorted section values — the left-hand list you flip through."""
    return [v for v in ctx.store.distinct(ctx.section_field) if v]


def list_items(ctx: LookupContext, section: str) -> list:
    """All lookup rows in one section, sorted by item, ready for the grid."""
    rows = ctx.store.list({ctx.section_field: section}, order=[(ctx.item_field, "asc")])
    return [_serialize(ctx, d) for d in rows if d.get(ctx.item_field)]


def field_options(ctx: LookupContext) -> dict:
    """Distinct existing values per editable field — seeds the autocomplete datalists so you
    can reuse a value or type a new one (sections/types are effectively an enum)."""
    return {c: [v for v in ctx.store.distinct(c) if v]
            for c in ctx.columns if c != ctx.item_field}


# --- write (with cascade) ---------------------------------------------------

def add_item(ctx: LookupContext, body: dict) -> dict:
    item = (body.get(ctx.item_field) or "").strip()
    section = (body.get(ctx.section_field) or "").strip()
    if not item:
        raise LookupError(f"{ctx.item_field} is required")
    if not section:
        raise LookupError(f"{ctx.section_field} is required")
    if ctx.store.one({ctx.item_field: item}):
        raise LookupError(f"{ctx.item_noun} '{item}' already exists", status=409)

    doc = {"_id": item}
    for c in ctx.columns:
        v = body.get(c)
        if isinstance(v, str):
            v = v.strip()
        if v not in (None, ""):
            doc[c] = v
    ctx.store.insert(doc)
    return {"ok": True, "id": doc["_id"], "row": _serialize(ctx, ctx.store.get(doc["_id"]))}


def update_item(ctx: LookupContext, body: dict) -> dict:
    """Edit one field of one lookup row, cascading to the target table.
    Body: {id, field, value}. Returns {ok, updated} (count of target rows touched)."""
    _id, fld = body.get("id"), body.get("field")
    value = body.get("value")
    if isinstance(value, str):
        value = value.strip()
    if not _id or not fld or fld not in ctx.columns:
        raise LookupError("bad id/field")

    doc = ctx.store.get(_id)
    if not doc:
        raise LookupError(f"{ctx.item_noun} not found", status=404)
    old_item = doc.get(ctx.item_field)

    # Rename: the item field is the match key on the target — re-point those rows too.
    if fld == ctx.item_field:
        if not value:
            raise LookupError(f"{ctx.item_field} cannot be blank")
        clash = ctx.store.one({ctx.item_field: value})
        if clash and clash["_id"] != _id:
            raise LookupError(f"{ctx.item_noun} '{value}' already exists", status=409)
        ctx.store.update(_id, {ctx.item_field: value})
        updated = ctx.target.update_where({ctx.target_match_field: old_item},
                                                {ctx.target_match_field: value})
        return {"ok": True, "updated": updated}

    # Plain field edit. Update the lookup row; cascade if the field is denormalized.
    ctx.store.update(_id, {fld: value or None})
    updated = 0
    if fld in ctx.cascade_fields:
        updated = ctx.target.update_where({ctx.target_match_field: old_item}, {fld: value or None})
    return {"ok": True, "updated": updated}


def delete_item(ctx: LookupContext, body: dict) -> dict:
    """Delete a lookup row. Blocked when target rows reference it, unless `reassign_to`
    names another item to re-point them onto first."""
    _id = body.get("id")
    reassign_to = (body.get("reassign_to") or "").strip()
    if not _id:
        raise LookupError("no id")
    doc = ctx.store.get(_id)
    if not doc:
        raise LookupError(f"{ctx.item_noun} not found", status=404)
    item = doc.get(ctx.item_field)

    in_use = ctx.target.count({ctx.target_match_field: item})
    if in_use and not reassign_to:
        raise LookupError(
            f"in use by {in_use} {ctx.target_noun}(s)", status=409, in_use=in_use)

    reassigned = 0
    if in_use and reassign_to:
        dest = ctx.store.one({ctx.item_field: reassign_to})
        if not dest:
            raise LookupError(f"reassign target '{reassign_to}' not found", status=404)
        cascade = {f: dest.get(f) for f in ctx.cascade_fields}
        reassigned = ctx.target.update_where(
            {ctx.target_match_field: item}, {ctx.target_match_field: reassign_to, **cascade})

    deletions.log(ctx.store.table, [doc])
    ctx.store.delete(_id)
    return {"ok": True, "deleted": 1, "reassigned": reassigned}
