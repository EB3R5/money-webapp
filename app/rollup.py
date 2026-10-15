"""Cashflow rollup — the one module that aggregates sum(Amount) over the transactions
store and owns the single Income/Expense classification rule.

Reports, the dashboard, and category-insights each used to hand-roll the same grouped
sum over transactions and re-decide what counts as Income vs Expense. That rule drifted:
the dashboard once bucketed by the *sign* of Amount while the reports bucketed by *Type*,
so the same month reported two different incomes. This module concentrates both the
aggregation shape and the classification behind one interface, so the rule lives — and is
tested — in exactly one place. It is the one owner of hand-written aggregation SQL over
transactions outside the store itself (ADR-0011).

Classification is by transaction **Type** ("Income" / "Expense"); everything else (e.g.
"Transfer") is neither. The rule is exposed both as reusable SUM expressions (for callers
that group by their own dimension, like the dashboard's per-month chart) and as the
income_expense() helper (for a single bucket, like the balance sheet's month figure).

Scope: every query takes the same keyword filters — `year`, `month` ("YYYY-MM"), `start`
and `end` (inclusive Date bounds), `where` (API key → value, or a list for IN, or None for
null-or-blank), `like` (API key → case-insensitive substring), `nonblank` (API keys that
must be present and non-empty), and `outflows` (Amount < 0 only).

The group-grain complement lives here too: group_kinds() classifies each ledger Group as
income or expense by the majority Type of its categories — the rule Budget-vs-Actual
favourability reads.
"""

from datetime import datetime
from typing import Optional, Sequence

from .store.base import _from_db, _to_db
from .store.categories import categories
from .store.transactions import transactions

INCOME = "Income"
EXPENSE = "Expense"

# A real date (ISO text) — the export nulls untypeable values, but the guard also keeps a
# stray non-date string out of the year/month arithmetic.
DATED = "date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'"
# Only real dated money movements with an amount take part in a rollup.
DATE_AMOUNT_GUARD = f"{DATED} AND amount IS NOT NULL"
AMOUNT_GUARD = "amount IS NOT NULL"

MONTH_EXPR = "substr(date, 1, 7)"
YEAR_EXPR = "CAST(substr(date, 1, 4) AS INTEGER)"


def _sum_if_type(type_value: str) -> str:
    """A SUM expression: Amount for rows of this Type, else 0."""
    return f"SUM(CASE WHEN type = '{type_value}' THEN amount ELSE 0 END)"


# Drop these into a SELECT to classify by Type consistently everywhere.
INCOME_SUM = _sum_if_type(INCOME)
EXPENSE_SUM = _sum_if_type(EXPENSE)


def _q(col: str) -> str:
    return '"' + col + '"'


def _like(text: str) -> str:
    return "%" + text.replace("%", r"\%").replace("_", r"\_") + "%"


def _scope(*, guard: str, year: Optional[int] = None, month: Optional[str] = None,
           start: Optional[datetime] = None, end: Optional[datetime] = None,
           where: Optional[dict] = None, like: Optional[dict] = None,
           nonblank: Sequence[str] = (), outflows: bool = False) -> tuple[str, list]:
    parts, params = [guard], []
    if year is not None:
        parts.append(f"{YEAR_EXPR} = ?")
        params.append(int(year))
    if month:
        parts.append(f"{MONTH_EXPR} = ?")
        params.append(month)
    if start is not None:
        parts.append("date >= ?")
        params.append(_to_db("datetime", start))
    if end is not None:
        parts.append("date <= ?")
        params.append(_to_db("datetime", end))
    if outflows:
        parts.append("amount < 0")
    for k, v in (like or {}).items():
        parts.append(f"{_q(transactions.column(k))} LIKE ? ESCAPE '\\' COLLATE NOCASE")
        params.append(_like(v))
    for k, v in (where or {}).items():
        col = _q(transactions.column(k))
        kind = transactions.kind(k)
        if v is None:
            parts.append(f"({col} IS NULL OR TRIM({col}) = '')")
        elif isinstance(v, (list, tuple, set)):
            vals = [_to_db(kind, x) for x in v]
            parts.append(f"{col} IN ({', '.join('?' for _ in vals)})")
            params.extend(vals)
        else:
            parts.append(f"{col} = ?")
            params.append(_to_db(kind, v))
    for k in nonblank:
        col = _q(transactions.column(k))
        parts.append(f"({col} IS NOT NULL AND TRIM({col}) <> '')")
    return " WHERE " + " AND ".join(parts), params


def _r2(v) -> float:
    return round(float(v or 0), 2)


def income_expense(*, year: Optional[int] = None, month: Optional[str] = None,
                         where: Optional[dict] = None) -> tuple[float, float]:
    """(income, expense) over the scoped transactions, classified by Type. Expense is
    returned positive (abs)."""
    clause, params = _scope(guard=DATE_AMOUNT_GUARD, year=year, month=month, where=where)
    rows = transactions.rows(
        f"SELECT {INCOME_SUM} AS income, {EXPENSE_SUM} AS expense FROM transactions{clause}",
        params)
    if not rows or rows[0]["income"] is None and rows[0]["expense"] is None:
        return 0.0, 0.0
    return _r2(rows[0]["income"]), _r2(abs(rows[0]["expense"] or 0))


def years() -> list[int]:
    """Distinct years present in the ledger, newest first — the year pickers on metrics,
    tax, and the P&L all read this."""
    rows = transactions.rows(
        f"SELECT DISTINCT {YEAR_EXPR} AS y FROM transactions WHERE {DATED} ORDER BY y DESC")
    return [int(r["y"]) for r in rows]


def totals_by(key: str, *, year: Optional[int] = None, month: Optional[str] = None,
                    start: Optional[datetime] = None, end: Optional[datetime] = None,
                    where: Optional[dict] = None, like: Optional[dict] = None,
                    outflows: bool = False, none_label: Optional[str] = None) -> list[dict]:
    """[{name, total}] = sum(Amount) grouped by `key`, most-negative first (biggest
    outflows lead). A null/blank key reads as `none_label`."""
    col = _q(transactions.column(key))
    clause, params = _scope(guard=AMOUNT_GUARD, year=year, month=month, start=start, end=end,
                            where=where, like=like, outflows=outflows)
    rows = transactions.rows(
        f"SELECT {col} AS k, SUM(amount) AS total FROM transactions{clause} "
        f"GROUP BY {col} ORDER BY SUM(amount)", params)
    return [{"name": r["k"] if r["k"] not in (None, "") else none_label, "total": _r2(r["total"])}
            for r in rows]


def totals_by_month(keys: str | Sequence[str], *, year: Optional[int] = None,
                          where: Optional[dict] = None,
                          nonblank: Sequence[str] = ()) -> list[dict]:
    """[{<key>…, month: "YYYY-MM", total, count}] = sum(Amount) grouped by the given
    key(s) plus calendar month, month ascending. Only dated rows with an amount take
    part; `year` restricts to one calendar year. The budget seeding maths and the P&L
    cells both read this instead of hand-rolling the month-dimensioned aggregation."""
    if isinstance(keys, str):
        keys = [keys]
    cols = [_q(transactions.column(k)) for k in keys]
    clause, params = _scope(guard=DATE_AMOUNT_GUARD, year=year, where=where, nonblank=nonblank)
    select = ", ".join(f"{c} AS k{i}" for i, c in enumerate(cols))
    # Group and order by the expression, not its alias: the table has a `month` column of
    # its own, and SQLite resolves a bare GROUP BY name to the column first.
    rows = transactions.rows(
        f"SELECT {select}, {MONTH_EXPR} AS mo, SUM(amount) AS total, COUNT(*) AS n "
        f"FROM transactions{clause} GROUP BY {', '.join(cols)}, {MONTH_EXPR} ORDER BY {MONTH_EXPR}",
        params)
    return [{**{k: r[f"k{i}"] for i, k in enumerate(keys)}, "month": r["mo"],
             "total": _r2(r["total"]), "count": int(r["n"])} for r in rows]


def grand_total(*, year: Optional[int] = None, month: Optional[str] = None,
                      start: Optional[datetime] = None, end: Optional[datetime] = None,
                      where: Optional[dict] = None, like: Optional[dict] = None) -> float:
    """sum(Amount) over the scoped transactions — the single grand-total figure."""
    clause, params = _scope(guard=AMOUNT_GUARD, year=year, month=month, start=start, end=end,
                            where=where, like=like)
    rows = transactions.rows(f"SELECT SUM(amount) AS total FROM transactions{clause}", params)
    return _r2(rows[0]["total"]) if rows else 0.0


def monthly_income_expense() -> list[dict]:
    """[{month, income, expense, net}] over every calendar month in the ledger, month
    ascending, classified by Type — the dashboard's cash-flow series. Expense is positive."""
    clause, params = _scope(guard=DATE_AMOUNT_GUARD)
    rows = transactions.rows(
        f"SELECT {MONTH_EXPR} AS mo, {INCOME_SUM} AS income, {EXPENSE_SUM} AS expense "
        f"FROM transactions{clause} GROUP BY {MONTH_EXPR} ORDER BY {MONTH_EXPR}", params)
    out = []
    for r in rows:
        income, expense = _r2(r["income"]), _r2(r["expense"])      # expense sums negative
        out.append({"month": r["mo"], "income": income, "expense": _r2(abs(expense)),
                    "net": _r2(income + expense)})
    return out


def date_span() -> tuple[Optional[datetime], Optional[datetime]]:
    """(earliest, latest) dated transaction, or (None, None) on an empty ledger."""
    rows = transactions.rows(
        f"SELECT MIN(date) AS lo, MAX(date) AS hi FROM transactions WHERE {DATED}")
    if not rows or rows[0]["lo"] is None:
        return None, None
    return _from_db("datetime", rows[0]["lo"]), _from_db("datetime", rows[0]["hi"])


def _in(values: Sequence[str]) -> tuple[str, list]:
    """A `category IN (...)` fragment, or a never-true one for an empty set."""
    vals = list(values)
    if not vals:
        return "0", []
    return f"category IN ({', '.join('?' for _ in vals)})", vals


def monthly_role_sums(income_categories: Sequence[str], savings_categories: Sequence[str],
                            *, year: Optional[int] = None) -> list[dict]:
    """[{month, income, savings}] month ascending: income = sum(Amount) over the income
    categories, savings = sum(|Amount|) over the savings categories (money moved into
    savings is never netted back out). The Savings rate and history read this."""
    inc_sql, inc_params = _in(income_categories)
    sav_sql, sav_params = _in(savings_categories)
    clause, params = _scope(guard=DATE_AMOUNT_GUARD, year=year)
    rows = transactions.rows(
        f"SELECT {MONTH_EXPR} AS mo, "
        f"SUM(CASE WHEN {inc_sql} THEN amount ELSE 0 END) AS income, "
        f"SUM(CASE WHEN {sav_sql} THEN abs(amount) ELSE 0 END) AS savings "
        f"FROM transactions{clause} GROUP BY {MONTH_EXPR} ORDER BY {MONTH_EXPR}",
        inc_params + sav_params + params)
    return [{"month": r["mo"], "income": _r2(r["income"]), "savings": _r2(r["savings"])}
            for r in rows]


def by_category(*, year: Optional[int] = None) -> list[dict]:
    """[{category, group, amount, absamt}] per non-blank Category: signed sum and the
    sum of |Amount| — the tax income/deduction rollup's raw material."""
    clause, params = _scope(guard=DATE_AMOUNT_GUARD, year=year, nonblank=["Category"])
    rows = transactions.rows(
        f"SELECT category, MAX({_q('group')}) AS grp, SUM(amount) AS amount, "
        f"SUM(abs(amount)) AS absamt FROM transactions{clause} GROUP BY category ORDER BY category",
        params)
    return [{"category": r["category"], "group": r["grp"], "amount": _r2(r["amount"]),
             "absamt": _r2(r["absamt"])} for r in rows]


def group_kinds() -> dict:
    """{ group: 'income' | 'expense' } by majority category Type in the group (from the
    categories store). Groups with no Income/Expense categories (e.g. all-Transfer)
    are absent; callers choose their own fallback."""
    rows = categories.rows(
        'SELECT "group" AS g, type AS t, COUNT(*) AS n FROM categories '
        'WHERE "group" IS NOT NULL AND TRIM("group") <> \'\' AND type IN (?, ?) '
        'GROUP BY "group", type', [INCOME, EXPENSE])
    tally: dict = {}
    for r in rows:
        tally.setdefault(r["g"], {INCOME: 0, EXPENSE: 0})[r["t"]] += int(r["n"])
    return {g: ("income" if c[INCOME] > c[EXPENSE] else "expense") for g, c in tally.items()}
