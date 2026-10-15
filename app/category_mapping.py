"""CategoryMapping — one deep module for a per-feature category→role table.

Savings (savings.py) and Tax (tax.py) each had the same dance: scan the ledger for the
distinct Category roster, append any missing categories to a mapping table with a
seed-guessed role, and upsert a hand-chosen role per category. The scan was byte-identical
and the sync differed only in the mapping store, the role field name, the seed rule, and
the default fields stamped on a freshly-synced row.

This module owns roster + sync + the role upsert once. Each feature constructs one adapter
declaring what differs: its `store`, `role_field`, allowed `roles`, `seed` rule, and the
`new_extra` fields a synced row carries. The bespoke reductions (savings wants two role-sets,
tax wants a dict with deduction fields) stay in the feature — those are genuinely per-feature
projections, not the shared dance. See CONTEXT.md: Category roster, Category mapping.

A mapping row's id is the Category name."""

from dataclasses import dataclass, field as dc_field
from typing import Callable

from .store.base import Store
from .store.transactions import transactions
from .web import DomainError


@dataclass
class CategoryMapping:
    store: Store
    role_field: str                                   # 'tax_role' | 'Savings_Role'
    roles: tuple                                       # allowed role values
    seed: Callable[[str, object, bool], str]           # (category, group, is_income) -> role
    new_extra: dict = dc_field(default_factory=dict)   # default fields on a freshly-synced row

    def roster(self) -> list:
        """[(category, group, is_income)] — the distinct ledger Category roster with each
        category's Group and whether any of its transactions is Type=="Income" (seed signal)."""
        return transactions.category_roster()

    def sync(self) -> dict:
        """Append any roster categories missing from the mapping, seeding each role. Existing
        roles are left untouched. Returns the count added."""
        existing = set(self.store.distinct("_id"))
        new_rows = []
        for category, group, is_income in self.roster():
            if category in existing:
                continue
            new_rows.append({
                "_id": category, "Category": category, "Group": group,
                self.role_field: self.seed(category, group, is_income),
                **self.new_extra,
            })
        if new_rows:
            self.store.insert_many(new_rows)
        return {"ok": True, "added": len(new_rows)}

    def docs(self) -> list[dict]:
        """The mapping rows, category-sorted — for a feature's projection."""
        return self.store.list(order=[("Category", "asc")])

    def set_role(self, body: dict, *, extra_fields: tuple = (),
                       role_required: bool = True) -> dict:
        """Upsert a category's role (and any declared extra fields). When `role_required` is
        False the role may be omitted to edit only the extra fields (tax notes-only edits)."""
        category = (body.get("category") or "").strip()
        if not category:
            raise DomainError("category is required")
        role = (body.get("role") or "").strip().upper()
        if (role_required or role) and role not in self.roles:
            raise DomainError(f"role must be one of {', '.join(self.roles)}")
        update = {"Category": category}
        if role:
            update[self.role_field] = role
        for f in extra_fields:
            if f in body:
                update[f] = (body[f] or "").strip() or None
        if self.store.get(category) is None:
            self.store.insert({"_id": category, **update})
        else:
            self.store.update(category, update)
        return {"ok": True, "category": category, "role": role or None}
