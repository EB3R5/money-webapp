"""Grid — the AG Grid Infinite-Row-Model datasource over one Store (ADR-0011).

The block/row/update/delete dance (block paging, sortModel, the search box, value
coercion, inline update, add row, delete-with-audit, full-row drill-down) with every
statement in the Store. Coercion comes from the Store's field kinds, so a router declares
only its columns, which of them are editable, which are searched, the default sort, and
optionally `derive`: the fields a write implies (the Ledger's Month from its Date), applied
to inline updates and added rows alike so a derived column never drifts from its source.
The Data page's read-only browse over any table is app/store/datatable.py.
"""

import secrets
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, List, Optional, Tuple

from django.urls import path

from . import web
from .store.base import Store, _to_db
from .store.deletions import deletions
from .web import DomainError

GridError = DomainError


def jsonable(v):
    """Make a Store value JSON-safe for the full-row detail view."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    return v


def parse_date(v):
    """ISO date/datetime string → datetime; blank → None; unparseable → ValueError."""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    s = str(v).replace("Z", "")
    try:
        return datetime.fromisoformat(s[:19])
    except ValueError:
        return datetime.combine(date.fromisoformat(s[:10]), datetime.min.time())


@dataclass
class Grid:
    store: Store
    columns: List[str]
    editable: Optional[List[str]] = None          # writable columns (default: all columns)
    search_keys: Optional[List[str]] = None       # default: the columns being served
    default_sort: Optional[List[Tuple[str, str]]] = None
    audit_name: Optional[str] = None              # delete-audit label (default: the table)
    derive: Optional[Callable] = None             # (fields about to be written) -> extra fields the
                                                  # write implies; applied to updates and added rows

    def __post_init__(self):
        if self.editable is None:
            self.editable = list(self.columns)

    # --- serialization -----------------------------------------------------------

    @staticmethod
    def _cell(v):
        if isinstance(v, datetime):
            return v.date().isoformat()
        if isinstance(v, date):
            return v.isoformat()
        return v

    def serialize(self, doc: dict) -> dict:
        out = {"_id": str(doc.get("_id"))}
        for c in self.columns:
            out[c] = self._cell(doc.get(c))
        return out

    # --- value coercion ------------------------------------------------------------

    def coerce(self, col: str, v):
        """Inbound grid value → typed value, by the Store's kind. Raises ValueError."""
        kind = self.store.kind(col)
        if kind == "real":
            if v in (None, "", "—"):
                return None
            return _to_db("real", v)
        if kind in ("date", "datetime"):
            return parse_date(v)
        if kind == "int":
            return None if v in (None, "") else _to_db("int", v)
        return (v.strip() or None) if isinstance(v, str) else v

    # --- datasource operations (Store-touching; testable directly) -------------------

    def block(self, body: dict) -> dict:
        start = int(body.get("startRow", 0))
        end = int(body.get("endRow", 100))
        limit = max(end - start, 1)

        sort = []
        for s in body.get("sortModel", []):
            cid = s.get("colId")
            if cid and cid in self.columns:
                sort.append((cid, "asc" if s.get("sort") == "asc" else "desc"))
        if not sort and self.default_sort:
            sort = list(self.default_sort)

        keys = self.search_keys if self.search_keys is not None else self.columns
        rows, total = self.store.search(
            body.get("q") or "", keys, order=sort, limit=limit, offset=start)
        return {"rows": [self.serialize(d) for d in rows], "lastRow": total}

    def update_field(self, body: dict) -> dict:
        _id, field, value = body.get("id"), body.get("field"), body.get("value")
        if not _id or field not in self.editable:
            raise GridError("bad id/field")
        try:
            val = self.coerce(field, value)
        except ValueError:
            raise GridError(f"{field} not a number")
        fields = {field: val}
        if self.derive:
            fields.update(self.derive(fields))
        return {"ok": self.store.update(_id, fields)}

    def create_row(self, body: dict, enrich: Optional[Callable] = None) -> dict:
        doc = {"_id": "man_" + secrets.token_hex(10)}
        for col in self.editable:
            if col in body:
                try:
                    doc[col] = self.coerce(col, body[col])
                except ValueError:
                    raise GridError(f"{col} not a number")
        if enrich:
            enrich(doc, body)
        if "Date" in self.columns and doc.get("Date") is None:
            doc["Date"] = datetime.combine(date.today(), datetime.min.time())
        if self.derive:
            doc.update(self.derive(doc))
        self.store.insert(doc)
        return {"ok": True, "id": doc["_id"], "row": self.serialize(self.store.get(doc["_id"]))}

    def delete_rows(self, body: dict) -> dict:
        ids = body.get("ids") or []
        if not ids:
            raise GridError("no ids")
        docs = [d for d in [self.store.get(i) for i in ids] if d is not None]
        deletions.log(self.audit_name or self.store.table, docs)
        deleted = self.store.delete_where(_id=[d["_id"] for d in docs]) if docs else 0
        return {"ok": True, "deleted": deleted}

    def get_doc(self, doc_id: str):
        """Full row by id, every field JSON-safe — for the row drill-down view."""
        doc = self.store.get(doc_id)
        return None if doc is None else {k: jsonable(v) for k, v in doc.items()}

    # --- route wiring ----------------------------------------------------------------

    def urlpatterns(self, seg: str, enrich: Optional[Callable] = None) -> list:
        """The Django routes for block/row/update/delete/doc under /api/{seg}, in the order
        FastAPI mounted them; a view module splices them into its own `urlpatterns`."""

        @web.POST
        def block(request):
            return web.json(self.block(web.read_json(request)))

        @web.GET
        def doc(request, doc_id: str):
            d = self.get_doc(doc_id)
            if d is None:
                return web.json({"error": "not found"}, 404)
            return web.json({"doc": d})

        @web.POST
        def row(request):
            return web.json(self.create_row(web.read_json(request), enrich))

        @web.POST
        def update(request):
            return web.json(self.update_field(web.read_json(request)))

        @web.POST
        def delete(request):
            return web.json(self.delete_rows(web.read_json(request)))

        return [path(f"api/{seg}", block), path(f"api/{seg}/doc/<str:doc_id>", doc),
                path(f"api/{seg}/row", row), path(f"api/{seg}/update", update),
                path(f"api/{seg}/delete", delete)]
