"""Store base: the field map and the CRUD every entity store shares (ADR-0011, ADR-0012).

A store declares its table and its FIELDS — one `Field` per column with the API key the
rest of the app and the JS islands use (spreadsheet-style, `"Account #"`), the snake_case
column, and the kind that decides typing. `to_row` and `to_api` are the single place a
column meets an API key. Every table carries `created_at`/`edited_at`, exposed as
`_created_at`/`_edited_at`, and `id`, exposed as both `_id` and `id`.

Kinds: text | real | int | bool | date | datetime | json. Dates and datetimes are stored as
ISO-8601 text and come back as `date`/`datetime` objects. JSON columns hold any JSON value.
A store may name a `spill` JSON column: API keys that match no field go there on write and
come back flattened on read (open-ended registries, config docs)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Iterable, Optional, Sequence

from .database import database

KINDS = ("text", "real", "int", "bool", "date", "datetime", "json")


@dataclass(frozen=True)
class Field:
    api: str
    col: str
    kind: str = "text"

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown kind {self.kind!r} for {self.api!r}")


TIMESTAMPS = (Field("_created_at", "created_at", "datetime"),
              Field("_edited_at", "edited_at", "datetime"))


def q(col: str) -> str:
    """Quote a column name (a few are SQL keywords: group, index, table)."""
    return '"' + col.replace('"', '""') + '"'


def _now() -> datetime:
    return datetime.now(UTC)


# --- value coercion --------------------------------------------------------------

def _to_db(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind == "text":
        return v if isinstance(v, str) else str(v)
    if kind == "real":
        if isinstance(v, bool):
            return float(v)
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "").replace("$", "")
        if s.endswith("%"):
            s = s[:-1]
        if s in ("", "-", "—"):
            return None
        neg = s.startswith("(") and s.endswith(")")
        if neg:
            s = s[1:-1]
        return -float(s) if neg else float(s)
    if kind == "int":
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip().replace(",", "")
        return int(float(s)) if s else None
    if kind == "bool":
        if isinstance(v, str):
            return 1 if v.strip().lower() in ("1", "true", "yes", "y") else 0
        return 1 if v else 0
    if kind == "date":
        if isinstance(v, datetime):
            return v.date().isoformat()
        if isinstance(v, date):
            return v.isoformat()
        s = str(v).strip()
        return s[:10] if s else None
    if kind == "datetime":
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, date):
            return datetime(v.year, v.month, v.day).isoformat()
        s = str(v).strip()
        return s or None
    if kind == "json":
        return json.dumps(v, default=_json_default, ensure_ascii=False)
    raise ValueError(kind)


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def _from_db(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind in ("text", "real"):
        return v
    if kind == "int":
        return int(v)
    if kind == "bool":
        return bool(v)
    if kind == "date":
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            return v
    if kind == "datetime":
        try:
            return datetime.fromisoformat(str(v))
        except ValueError:
            return v
    if kind == "json":
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v
    raise ValueError(kind)


# --- the store --------------------------------------------------------------------

class Store:
    """One entity's SQL. Subclass or instantiate with a table and fields; add the entity's
    own queries as methods on a subclass. Routers never see a statement."""

    table: str = ""
    fields: Sequence[Field] = ()
    spill: Optional[str] = None      # JSON column receiving unmapped API keys, if any
    id_api_keys = ("_id", "id")

    def __init__(self, table: str = "", fields: Sequence[Field] = (), spill: Optional[str] = None):
        if table:
            self.table = table
        if fields:
            self.fields = tuple(fields)
        if spill is not None:
            self.spill = spill
        all_fields = tuple(self.fields) + TIMESTAMPS
        self._by_api = {f.api: f for f in all_fields}
        self._by_col = {f.col: f for f in all_fields}
        self.columns = ("id",) + tuple(f.col for f in all_fields)
        self.db = database

    # --- mapping -------------------------------------------------------------------

    def api_keys(self) -> list[str]:
        return [f.api for f in self.fields]

    def column(self, api_key: str) -> str:
        """The column behind an API key (or a column name passed through) — for the few
        owners of hand-written aggregations, like the cashflow rollup."""
        return self._col(api_key)

    def kind(self, api_key: str) -> str:
        """The declared kind of an API key (`text` for the id keys)."""
        if api_key in self.id_api_keys:
            return "text"
        f = self._by_api.get(api_key)
        if f is None:
            raise KeyError(f"{self.table}: no field {api_key!r}")
        return f.kind

    def to_row(self, api: dict, *, strict: bool = False) -> tuple[dict, dict]:
        """API-shaped dict -> (column dict, leftovers). Leftovers are API keys with no field;
        with a spill column they are returned for the caller to store there; without one
        they are dropped, or rejected when `strict`."""
        row: dict = {}
        leftovers: dict = {}
        for k, v in api.items():
            if k in self.id_api_keys:
                row["id"] = None if v is None else str(v)
                continue
            f = self._by_api.get(k)
            if f is None:
                leftovers[k] = v
                continue
            row[f.col] = _to_db(f.kind, v)
        if leftovers and self.spill is None and strict:
            raise ValueError(f"{self.table}: unknown fields {sorted(leftovers)}")
        return row, leftovers

    def to_api(self, row) -> dict:
        """sqlite Row -> API-shaped dict (typed values, JSON parsed, spill flattened)."""
        out: dict = {}
        spill_val = None
        for col in row.keys():
            v = row[col]
            if col == "id":
                out["_id"] = v
                out["id"] = v
                continue
            if col == self.spill:
                spill_val = _from_db("json", v)
                continue
            f = self._by_col.get(col)
            out[f.api if f else col] = _from_db(f.kind, v) if f else v
        if isinstance(spill_val, dict):
            for k, v in spill_val.items():
                out.setdefault(k, v)
        return out

    def _prepare_insert(self, api: dict) -> dict:
        row, leftovers = self.to_row(api)
        if not row.get("id"):
            row["id"] = uuid.uuid4().hex
        if self.spill:
            existing = row.get(self.spill)
            merged = json.loads(existing) if isinstance(existing, str) else {}
            merged.update(leftovers)
            row[self.spill] = _to_db("json", merged) if merged else None
        row.setdefault("created_at", _to_db("datetime", _now()))
        return row

    # --- CRUD ----------------------------------------------------------------------

    def get(self, id_: str) -> Optional[dict]:
        with self.db.acquire() as conn:
            cur = conn.execute(f"SELECT * FROM {q(self.table)} WHERE id = ?", (id_,))
            r = cur.fetchone()
            return self.to_api(r) if r else None

    def insert(self, api: dict) -> str:
        row = self._prepare_insert(api)
        cols = list(row.keys())
        sql = (f"INSERT INTO {q(self.table)} ({', '.join(q(c) for c in cols)}) "
               f"VALUES ({', '.join('?' for _ in cols)})")
        with self.db.acquire() as conn:
            conn.execute(sql, [row[c] for c in cols])
        return row["id"]

    def insert_many(self, items: Iterable[dict]) -> list[str]:
        ids = []
        with self.db.scope():
            for api in items:
                ids.append(self.insert(api))
        return ids

    def upsert(self, api: dict, *, protect: Sequence[str] = ()) -> str:
        """Insert, or update an existing id. `protect` names API keys never overwritten on
        an existing row (app-owned fields the Sheets import must not clobber)."""
        row, leftovers = self.to_row(api)
        id_ = row.get("id")
        if id_ and self.get(id_) is not None:
            updates = {k: v for k, v in api.items()
                       if k not in self.id_api_keys and k not in protect}
            self.update(id_, updates)
            return id_
        return self.insert(api)

    def update(self, id_: str, updates: dict) -> bool:
        """Dirty-diff: set exactly the fields given (ADR-0007). Unknown keys go to the spill
        column when there is one, else are ignored. Returns whether a row matched."""
        row, leftovers = self.to_row(updates)
        row.pop("id", None)
        if self.spill and leftovers:
            current = self.get(id_)
            if current is None:
                return False
            keep = {k: v for k, v in current.items()
                    if k not in self._by_api and k not in self.id_api_keys}
            keep.update(leftovers)
            row[self.spill] = _to_db("json", keep)
        row["edited_at"] = _to_db("datetime", _now())
        sets = ", ".join(f"{q(c)} = ?" for c in row)
        with self.db.acquire() as conn:
            cur = conn.execute(
                f"UPDATE {q(self.table)} SET {sets} WHERE id = ?", [*row.values(), id_])
            return cur.rowcount > 0

    def update_where(self, where: dict, updates: dict) -> int:
        """Set the given API-keyed fields on every row matching `where` (equality / IN /
        null-or-blank per `_where`); returns the number of rows touched. The lookup
        cascade's one write shape (ADR-0006)."""
        row, _leftovers = self.to_row(updates)
        row.pop("id", None)
        if not row:
            return 0
        row["edited_at"] = _to_db("datetime", _now())
        sets = ", ".join(f"{q(c)} = ?" for c in row)
        clause, params = self._where(where)
        with self.db.acquire() as conn:
            cur = conn.execute(
                f"UPDATE {q(self.table)} SET {sets}{clause}", [*row.values(), *params])
            return cur.rowcount

    def delete(self, id_: str) -> Optional[dict]:
        """Hard delete; returns the row as it was (callers audit it first, ADR-0005)."""
        doc = self.get(id_)
        if doc is None:
            return None
        with self.db.acquire() as conn:
            conn.execute(f"DELETE FROM {q(self.table)} WHERE id = ?", (id_,))
        return doc

    def delete_where(self, **where) -> int:
        clause, params = self._where(where)
        with self.db.acquire() as conn:
            cur = conn.execute(f"DELETE FROM {q(self.table)}{clause}", params)
            return cur.rowcount

    # --- queries -------------------------------------------------------------------

    def _col(self, api_or_col: str) -> str:
        f = self._by_api.get(api_or_col)
        if f:
            return f.col
        if api_or_col in self.id_api_keys:
            return "id"
        if api_or_col in self._by_col:
            return api_or_col
        raise KeyError(f"{self.table}: no field {api_or_col!r}")

    def _where(self, where: Optional[dict]) -> tuple[str, list]:
        if not where:
            return "", []
        parts, params = [], []
        for k, v in where.items():
            col = self._col(k)
            f = self._by_col.get(col)
            if v is None:
                parts.append(f"{q(col)} IS NULL")
            elif isinstance(v, (list, tuple, set)):
                vals = [_to_db(f.kind, x) if f else x for x in v]
                parts.append(f"{q(col)} IN ({', '.join('?' for _ in vals)})")
                params.extend(vals)
            else:
                parts.append(f"{q(col)} = ?")
                params.append(_to_db(f.kind, v) if f else v)
        return " WHERE " + " AND ".join(parts), params

    def _order(self, order: Optional[Sequence[tuple[str, str]]]) -> str:
        if not order:
            return ""
        return " ORDER BY " + ", ".join(
            f"{q(self._col(k))} {'DESC' if str(d).lower().startswith('d') or d == -1 else 'ASC'}"
            for k, d in order)

    def list(self, where: Optional[dict] = None,
                   order: Optional[Sequence[tuple[str, str]]] = None,
                   limit: Optional[int] = None, offset: int = 0) -> list[dict]:
        clause, params = self._where(where)
        sql = f"SELECT * FROM {q(self.table)}{clause}{self._order(order)}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [int(limit), int(offset)]
        with self.db.acquire() as conn:
            cur = conn.execute(sql, params)
            return [self.to_api(r) for r in cur.fetchall()]

    def one(self, where: Optional[dict] = None,
                  order: Optional[Sequence[tuple[str, str]]] = None) -> Optional[dict]:
        rows = self.list(where, order, limit=1)
        return rows[0] if rows else None

    def count(self, where: Optional[dict] = None) -> int:
        clause, params = self._where(where)
        with self.db.acquire() as conn:
            cur = conn.execute(f"SELECT COUNT(*) FROM {q(self.table)}{clause}", params)
            return int((cur.fetchone())[0])

    def distinct(self, key: str, where: Optional[dict] = None) -> list:
        col = self._col(key)
        f = self._by_col.get(col)
        clause, params = self._where(where)
        with self.db.acquire() as conn:
            cur = conn.execute(
                f"SELECT DISTINCT {q(col)} FROM {q(self.table)}{clause} ORDER BY {q(col)}", params)
            return [_from_db(f.kind, r[0]) if f else r[0] for r in cur.fetchall()]

    def search(self, text: str, keys: Sequence[str], *,
                     where: Optional[dict] = None,
                     order: Optional[Sequence[tuple[str, str]]] = None,
                     limit: Optional[int] = None, offset: int = 0) -> tuple[list[dict], int]:
        """Case-insensitive substring search over `keys` (ADR-0012: LIKE, not FTS).
        Returns (rows, total matching)."""
        clause, params = self._where(where)
        text = (text or "").strip()
        if text:
            like = "%" + text.replace("%", r"\%").replace("_", r"\_") + "%"
            ors = " OR ".join(f"{q(self._col(k))} LIKE ? ESCAPE '\\' COLLATE NOCASE" for k in keys)
            clause = (clause + " AND " if clause else " WHERE ") + f"({ors})"
            params = params + [like] * len(keys)
        with self.db.acquire() as conn:
            cur = conn.execute(f"SELECT COUNT(*) FROM {q(self.table)}{clause}", params)
            total = int((cur.fetchone())[0])
            sql = f"SELECT * FROM {q(self.table)}{clause}{self._order(order)}"
            p = list(params)
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                p += [int(limit), int(offset)]
            cur = conn.execute(sql, p)
            return [self.to_api(r) for r in cur.fetchall()], total

    def rows(self, sql: str, params: Sequence = ()) -> list:
        """Escape hatch for a store's own statements (aggregations). Returns sqlite Rows."""
        with self.db.acquire() as conn:
            cur = conn.execute(sql, list(params))
            return cur.fetchall()
