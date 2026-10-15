"""Transactions — the ledger spine. Spreadsheet-style API keys (Tiller columns) map onto
snake_case columns; Category and its derived fields are app-owned (ADR-0006)."""

from datetime import UTC, date, datetime, timedelta
from typing import Optional, Sequence

from .base import _from_db, _to_db, Field, Store, q

TABLE = 'transactions'

FIELDS = (
    Field('Transaction ID', 'transaction_id', 'text'),
    Field('Date', 'date', 'datetime'),
    Field('Description', 'description', 'text'),
    Field('Full Description', 'full_description', 'text'),
    Field('Amount', 'amount', 'real'),
    Field('Account', 'account', 'text'),
    Field('Account #', 'account_number', 'text'),
    Field('Institution', 'institution', 'text'),
    Field('Month', 'month', 'datetime'),
    Field('Week', 'week', 'datetime'),
    Field('Category', 'category', 'text'),
    Field('Group', 'group', 'text'),
    Field('Budget', 'budget', 'text'),
    Field('Cashflow Type', 'cashflow_type', 'text'),
    Field('Timing', 'timing', 'text'),
    Field('Type', 'type', 'text'),
    Field('Categorized Date', 'categorized_date', 'datetime'),
    Field('Check Number', 'check_number', 'text'),
    Field('Metadata', 'metadata', 'text'),
    Field('Pred:Category', 'pred_category', 'text'),
    Field('Pred:Conf', 'pred_conf', 'json'),
    # Feed provenance (ADR-0014): NULL on Tiller rows.
    Field('source', 'source', 'text'),
    Field('provider_account_id', 'provider_account_id', 'text'),
    Field('provider_txn_id', 'provider_txn_id', 'text'),
    Field('pending', 'pending', 'bool'),
    Field('posted_at', 'posted_at', 'datetime'),
    Field('last_seen_at', 'last_seen_at', 'datetime'),
    # The feed's last-applied provider values, {field: normalized value} (ADR-0019): what a
    # Sync run compares against to keep a hand edit and still apply a bank change.
    Field('_provider', 'provider_values', 'json'),
)

# The provider fields the feed snapshots (ADR-0019). Month is derived from Date, not snapshotted.
SNAPSHOT_FIELDS = ("Date", "posted_at", "Description", "Full Description", "Amount", "Account",
                   "Institution", "pending", "Metadata")
# The provider fields a person can edit on the Ledger — the ones a hand edit can exist on.
HAND_EDITABLE = ("Date", "Description", "Amount", "Account", "Institution")

# A Transaction still to categorize: no Category, or a blank one.
BLANK_CATEGORY = "(category IS NULL OR TRIM(category) = '')"


def month_of(day) -> Optional[datetime]:
    """The Ledger's Month for a Date: the first of that month at midnight. Derived, never
    typed: the feed sets it from the posted day, the Ledger from an edited or added Date."""
    if isinstance(day, datetime):
        return datetime(day.year, day.month, 1)
    if isinstance(day, date):
        return datetime(day.year, day.month, 1)
    return None


def derive_month(fields: dict) -> dict:
    """What a Ledger write of `fields` implies: Month follows Date whenever Date is written."""
    return {"Month": month_of(fields["Date"])} if "Date" in fields else {}


def _kind_of(field: str) -> str:
    for f in FIELDS:
        if f.api == field:
            return f.kind
    return "text"


def provider_norm(field: str, value):
    """One provider value in the form the snapshot stores and every comparison uses:
    datetimes as naive-UTC ISO seconds (a date → midnight, an aware datetime → UTC, a stored
    ISO string parsed first), reals as float, bools as bool, text with blank == missing."""
    if value is None:
        return None
    kind = _kind_of(field)
    if kind in ("datetime", "date"):
        v = value
        if isinstance(v, str):
            v = _from_db("datetime", v)
            if isinstance(v, str):
                return v                          # unparseable text: compare as is
        if isinstance(v, datetime):
            if v.tzinfo is not None:
                v = v.astimezone(UTC).replace(tzinfo=None)
        elif isinstance(v, date):
            v = datetime(v.year, v.month, v.day)
        else:
            return str(v)
        return v.isoformat(timespec="seconds")
    if kind == "real":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if kind == "bool":
        return bool(value)
    if kind == "int":
        return int(value)
    return value or None


def provider_same(field: str, a, b) -> bool:
    """Equality of two normalized provider values; Amount within a hair, never ==."""
    if _kind_of(field) == "real" and isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-9
    return a == b


def hand_edits(row: dict) -> dict:
    """{field: the row's value} for every snapshot field whose stored value differs from the
    feed's last-applied value — the person's edits. Empty when the row has no snapshot."""
    snap = row.get("_provider")
    if not isinstance(snap, dict):
        return {}
    return {f: row.get(f) for f in SNAPSHOT_FIELDS
            if not provider_same(f, provider_norm(f, row.get(f)), snap.get(f))}


def provider_value(row: dict, field: str):
    """The bank's value of a field regardless of hand edits: the snapshot's when the row has
    one, else the row's own (normalized)."""
    snap = row.get("_provider")
    if isinstance(snap, dict) and field in snap:
        return snap[field]
    return provider_norm(field, row.get(field))


class TransactionsStore(Store):
    def blank(self) -> list[dict]:
        """Every Transaction with a blank Category, oldest first — what the Rule engine and
        the ML suggestion pass scan."""
        rows = self.rows(
            f"SELECT * FROM transactions WHERE {BLANK_CATEGORY} ORDER BY date, rowid")
        return [self.to_api(r) for r in rows]

    def blank_among(self, ids: Sequence[str]) -> list[dict]:
        """The blank-Category rows among `ids`, oldest first — what the feed categorizes
        right after inserting them."""
        ids = list(ids)
        if not ids:
            return []
        rows = self.rows(
            f"SELECT * FROM transactions WHERE {BLANK_CATEGORY} "
            f"AND id IN ({', '.join('?' for _ in ids)}) ORDER BY date, rowid", ids)
        return [self.to_api(r) for r in rows]

    def for_matching(self) -> list[dict]:
        """The columns the Rule engine reads, for every Transaction, newest first — the
        preview's one in-process scan."""
        rows = self.rows(
            "SELECT id, date, description, account, institution, amount, category "
            "FROM transactions ORDER BY date DESC, rowid DESC")
        return [self.to_api(r) for r in rows]

    def pending_twins(self, provider_account_id: str, *, posted_day: datetime,
                            exclude_txn_id: str, days: int = 3) -> list[dict]:
        """Pending feed rows in the same provider account with a Date within ±`days` of
        `posted_day`, other than the row with `exclude_txn_id` — the candidates a newly
        posted Transaction may have replaced. The Amount is matched by the caller on the
        bank's value (`provider_value`), so a hand-edited pending row still finds its twin."""
        lo = _to_db("datetime", posted_day - timedelta(days=days))
        hi = _to_db("datetime", posted_day + timedelta(days=days))
        rows = self.rows(
            "SELECT * FROM transactions WHERE source = 'simplefin' AND pending = 1 "
            "AND provider_account_id = ? AND provider_txn_id <> ? "
            "AND date >= ? AND date <= ? ORDER BY date, rowid",
            [provider_account_id, exclude_txn_id, lo, hi])
        return [self.to_api(r) for r in rows]

    def stale_pending(self, provider_account_id: str, *, window_start: datetime,
                            window_end: datetime, unseen_since: datetime) -> list[dict]:
        """Pending feed rows dated inside the window that no run has seen since `unseen_since`."""
        rows = self.rows(
            "SELECT * FROM transactions WHERE source = 'simplefin' AND pending = 1 "
            "AND provider_account_id = ? AND date >= ? AND date < ? AND last_seen_at < ? "
            "ORDER BY date, rowid",
            [provider_account_id, _to_db("datetime", window_start), _to_db("datetime", window_end),
             _to_db("datetime", unseen_since)])
        return [self.to_api(r) for r in rows]

    def dated_amounts(self, *, group: str) -> list[tuple]:
        """[(Date, Amount)] for every dated, non-null-amount transaction in a Group — what
        the Credit page sums into its payment totals."""
        sql = (f"SELECT date, amount FROM {q(self.table)} WHERE {q('group')} = ? "
               f"AND date IS NOT NULL AND amount IS NOT NULL")
        return [(_from_db("datetime", r[0]), r[1]) for r in self.rows(sql, (group,))]

    def insights(self, *, start: Optional[datetime] = None, end: Optional[datetime] = None,
                       text: Optional[str] = None, group: Optional[object] = ...,
                       category: Optional[object] = ..., limit: int = 500) -> tuple[list[dict], int]:
        """(rows, total) for the Category Insights detail panel: dated rows with an Amount
        inside the inclusive Date range, Description containing `text`, and — when given —
        the exact Group / Category (None means null-or-blank). Most-negative first, capped."""
        parts, params = ["amount IS NOT NULL"], []
        if start is not None:
            parts.append("date >= ?"); params.append(_to_db("datetime", start))
        if end is not None:
            parts.append("date <= ?"); params.append(_to_db("datetime", end))
        if text:
            like = "%" + text.replace("%", r"\%").replace("_", r"\_") + "%"
            parts.append("description LIKE ? ESCAPE '\\' COLLATE NOCASE"); params.append(like)
        for col, val in ((q("group"), group), ("category", category)):
            if val is ...:
                continue
            if val is None:
                parts.append(f"({col} IS NULL OR TRIM({col}) = '')")
            else:
                parts.append(f"{col} = ?"); params.append(val)
        clause = " WHERE " + " AND ".join(parts)
        total = int((self.rows(f"SELECT COUNT(*) FROM transactions{clause}", params))[0][0])
        rows = self.rows(
            f"SELECT id, date, category, description, amount FROM transactions{clause} "
            f"ORDER BY amount, rowid LIMIT ?", params + [int(limit)])
        return [self.to_api(r) for r in rows], total

    def category_roster(self) -> list[tuple]:
        """[(category, group, is_income)] — every distinct non-blank Category with its
        Group and whether any of its rows is Type == 'Income' (the mapping seed signal)."""
        rows = self.rows(
            f"SELECT category, MAX({q('group')}) AS grp, "
            "MAX(CASE WHEN type = 'Income' THEN 1 ELSE 0 END) AS income "
            f"FROM {q(self.table)} WHERE NOT {BLANK_CATEGORY} GROUP BY category ORDER BY category")
        return [(r["category"], r["grp"], bool(r["income"])) for r in rows]

    def count_blank(self) -> int:
        rows = self.rows(f"SELECT COUNT(*) FROM transactions WHERE {BLANK_CATEGORY}")
        return int(rows[0][0])

    def labelled(self, *, accounts: Optional[Sequence[str]] = None,
                       start: Optional[datetime] = None,
                       end: Optional[datetime] = None) -> list[dict]:
        """Categorized Transactions for ML training: text fields, Amount, Category, filtered
        by Account and an inclusive Date range."""
        sql = ("SELECT id, description, full_description, amount, category FROM transactions "
               f"WHERE NOT {BLANK_CATEGORY}")
        params: list = []
        if accounts:
            sql += f" AND account IN ({', '.join('?' for _ in accounts)})"
            params.extend(accounts)
        if start is not None:
            sql += " AND date >= ?"
            params.append(_to_db("datetime", start))
        if end is not None:
            sql += " AND date <= ?"
            params.append(_to_db("datetime", end))
        return [self.to_api(r) for r in self.rows(sql, params)]


transactions = TransactionsStore(TABLE, FIELDS)
