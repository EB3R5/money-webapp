"""DataTable — the generic read datasource over any app-owned table (the Data page).

Tables come from the live schema (`sqlite_master`) minus a hidden set of internal and
credential tables; columns from `PRAGMA table_info`. One block query does ORDER BY / LIMIT /
OFFSET plus a case-insensitive LIKE across the table's TEXT columns. Every table and column
name in a statement is validated against the schema first, so a route parameter never
reaches SQL unchecked. When an entity store exists for the table, its field map supplies
the display keys (`"Account #"` rather than `account_number`); otherwise the raw column
names show. Writes are not here: the one editable table (autocat) is edited through its
own Store by the router."""

from __future__ import annotations

import importlib
import pkgutil
from typing import Optional

from . import database as _database_module
from .base import Store, _from_db, q
from .database import database

HIDDEN = frozenset({"model_versions", "sync_state", "app_health", "schema_version",
                    "blobs"})
EDITABLE = frozenset({"autocat"})


def _stores_by_table() -> dict[str, Store]:
    """{table: Store} for every entity store module under app.store."""
    import app.store as pkg
    out: dict[str, Store] = {}
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name in ("base", "blobs", "database", "datatable", "files", "permissions", "schema"):
            continue
        mod = importlib.import_module(f"app.store.{m.name}")
        for v in vars(mod).values():
            if isinstance(v, Store) and v.table:
                out.setdefault(v.table, v)
    return out


class DataTable:
    def __init__(self):
        self._stores: Optional[dict[str, Store]] = None

    def store_for(self, table: str) -> Optional[Store]:
        if self._stores is None:
            self._stores = _stores_by_table()
        return self._stores.get(table)

    def tables(self) -> list[dict]:
        """[{name, count}] of every browsable table, alphabetical."""
        out = []
        for name in database.tables():
            if name in HIDDEN or name.startswith("sqlite_"):
                continue
            with database.acquire() as conn:
                cur = conn.execute(f"SELECT COUNT(*) FROM {q(name)}")
                n = int((cur.fetchone())[0])
            out.append({"name": name, "count": n, "editable": name in EDITABLE})
        return out

    def exists(self, table: str) -> bool:
        return table not in HIDDEN and not table.startswith("sqlite_") and table in database.tables()

    def columns(self, table: str) -> list[dict]:
        """[{col, key, kind}] from PRAGMA table_info, in column order, minus `id` and the
        timestamps; `key` is the store's API key when a store exists, else the column."""
        store = self.store_for(table)
        with database.acquire() as conn:
            cur = conn.execute(f"PRAGMA table_info({q(table)})")
            info = cur.fetchall()
        out = []
        for r in info:
            col, decl = r[1], (r[2] or "").upper()
            if col in ("id", "created_at", "edited_at"):
                continue
            key = store._by_col[col].api if store and col in store._by_col else col
            kind = store._by_col[col].kind if store and col in store._by_col else (
                "real" if decl in ("REAL", "INTEGER", "NUMERIC") else "text")
            out.append({"col": col, "key": key, "kind": kind, "text": decl in ("", "TEXT")})
        return out

    def _to_api(self, table: str, cols: list[dict], row) -> dict:
        store = self.store_for(table)
        if store is not None:
            return store.to_api(row)
        out = {"_id": row["id"], "id": row["id"]}
        for c in cols:
            out[c["key"]] = row[c["col"]]
        return out

    @staticmethod
    def _cell(v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if isinstance(v, (dict, list)):
            return str(v)
        return v

    def block(self, table: str, body: dict) -> dict:
        """AG Grid Infinite Row Model block: {rows, lastRow}, every column serialized."""
        cols = self.columns(table)
        by_key = {c["key"]: c for c in cols}
        start = int(body.get("startRow", 0))
        end = int(body.get("endRow", 100))
        limit = max(end - start, 1)
        text = (body.get("q") or "").strip()
        where, params = "", []
        text_cols = [c["col"] for c in cols if c["text"]]
        if text and text_cols:
            like = "%" + text.replace("%", r"\%").replace("_", r"\_") + "%"
            where = " WHERE " + " OR ".join(f"{q(c)} LIKE ? ESCAPE '\\' COLLATE NOCASE" for c in text_cols)
            params = [like] * len(text_cols)
        order = ""
        for s in body.get("sortModel", []):
            c = by_key.get(s.get("colId"))
            if c:
                order = f" ORDER BY {q(c['col'])} {'ASC' if s.get('sort') == 'asc' else 'DESC'}"
                break
        if not order:
            order = " ORDER BY rowid"
        with database.acquire() as conn:
            cur = conn.execute(f"SELECT COUNT(*) FROM {q(table)}{where}", params)
            total = int((cur.fetchone())[0])
            cur = conn.execute(
                f"SELECT * FROM {q(table)}{where}{order} LIMIT ? OFFSET ?", [*params, limit, start])
            rows = cur.fetchall()
        out = []
        for r in rows:
            api = self._to_api(table, cols, r)
            out.append({"_id": str(api.get("_id")), **{c["key"]: self._cell(api.get(c["key"])) for c in cols}})
        return {"rows": out, "lastRow": total}

    def get(self, table: str, row_id: str) -> Optional[dict]:
        cols = self.columns(table)
        with database.acquire() as conn:
            cur = conn.execute(f"SELECT * FROM {q(table)} WHERE id = ?", (row_id,))
            r = cur.fetchone()
        if r is None:
            return None
        api = self._to_api(table, cols, r)
        return {k: self._cell(v) for k, v in api.items()}


datatable = DataTable()
