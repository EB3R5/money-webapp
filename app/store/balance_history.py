"""Balance history — dated Snapshots of an Account's Balance (append-only, app/snapshot.py).

`Type` is the coarse, category-derived kind (Assets / Liabilities / Equity) the balance sheet
and the account-category cascade read; `Account Type` is the granular kind the Balances grid
shows (Checking Account, Common Stock, ...). `Class` is Tiller's Asset / Liability label."""

from datetime import datetime
from typing import Sequence

from .base import Field, Store, _from_db, q


def _dt(v):
    return _from_db("datetime", v)

TABLE = 'balance_history'

FIELDS = (
    Field('Account ID', 'account_id', 'text'),
    Field('Account', 'account', 'text'),
    Field('Account #', 'account_number', 'text'),      # Tiller history only; feed rows carry none
    Field('Institution', 'institution', 'text'),
    Field('Date', 'date', 'datetime'),
    Field('Balance', 'balance', 'real'),
    Field('Class', 'class', 'text'),
    Field('Group', 'group', 'text'),
    Field('Category', 'category', 'text'),
    Field('Type', 'type', 'text'),
    Field('Account Type', 'account_type', 'text'),
    Field('Month', 'month', 'text'),
    Field('Week', 'week', 'text'),
    Field('Time', 'time', 'text'),
    Field('Index', 'index', 'text'),
    Field('Updated', 'updated', 'text'),
    Field('ML Confidence', 'ml_confidence', 'text'),
    Field('ML Source', 'ml_source', 'text'),
    Field('_src', 'source', 'text'),
    Field('sync_run_id', 'sync_run_id', 'text'),   # one Snapshot per Account per feed run
    Field('available', 'available', 'real'),
)


class BalanceHistoryStore(Store):
    def latest_for_account(self, account_id: str) -> dict | None:
        """The newest Snapshot of an Account, by Account ID."""
        return self.one({"Account ID": account_id}, order=[("Date", "desc")])

    def latest_by_account(self) -> dict:
        """{Account name: {"balance", "date"}} — the newest Snapshot per named account."""
        sql = (f"SELECT b.account, b.balance, b.date FROM {q(self.table)} b "
               f"WHERE b.account IS NOT NULL AND b.account != '' AND b.date IS NOT NULL "
               f"AND b.date = (SELECT MAX(date) FROM {q(self.table)} WHERE account = b.account) "
               f"ORDER BY b.account")
        out = {}
        for r in self.rows(sql):
            out[r[0]] = {"balance": r[1], "date": _dt(r[2])}
        return out

    def months(self) -> list[tuple[int, int]]:
        """(year, month) pairs present in the history, newest first — the balance sheet's
        month picker."""
        rows = self.rows(
            f"SELECT DISTINCT substr(date, 1, 7) AS ym FROM {q(self.table)} "
            "WHERE date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-*' ORDER BY ym DESC")
        return [(int(r[0][:4]), int(r[0][5:7])) for r in rows]

    def in_month(self, year: int, month: int) -> list[dict]:
        """Every Snapshot with a Balance dated in the calendar month, oldest first — the rows
        the balance sheet reduces to starting / ending / max per account."""
        return self.list_where_sql(
            f"substr(date, 1, 7) = ? AND balance IS NOT NULL", [f"{year:04d}-{month:02d}"],
            order="date, rowid")

    def list_where_sql(self, clause: str, params: list, *, order: str = "rowid") -> list[dict]:
        rows = self.rows(f"SELECT * FROM {q(self.table)} WHERE {clause} ORDER BY {order}", params)
        return [self.to_api(r) for r in rows]

    def account_names(self) -> list[str]:
        """Distinct non-blank Account names, sorted."""
        return [a for a in self.distinct("Account") if a]

    def accounts_with_rows_since(self, since: datetime, *, exclude_src: Sequence[str] = ()) -> set[str]:
        """Account names that have a Snapshot dated on or after `since`, ignoring rows from
        the given sources (a sync skips an account a person has stamped this month)."""
        sql = f"SELECT DISTINCT account FROM {q(self.table)} WHERE date >= ? AND account IS NOT NULL"
        params: list = [since.isoformat()]
        if exclude_src:
            sql += f" AND (source IS NULL OR source NOT IN ({', '.join('?' for _ in exclude_src)}))"
            params += list(exclude_src)
        return {r[0] for r in self.rows(sql, params)}


balance_history = BalanceHistoryStore(TABLE, FIELDS)
