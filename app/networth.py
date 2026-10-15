"""Net worth — the one owner of the balance-sheet arithmetic (ADR-0021, D2).

The Balance Sheet page used to reduce a month's Snapshots to per-account rows and sum them
inside its router. The Planning pages need the same figure for any month, with a sensible
answer for a month that has no Snapshots, so the reduction lives here and the balance sheet
imports it. One rule: net worth as of a month is each account's *ending* Snapshot in that
calendar month, assets (Assets + Equity, which holds brokerage holdings) minus the absolute
value of liabilities — exactly what the balance sheet shows for that month.

An account with no Snapshot in the month is not part of that month's figure, on either page.
"""

from .store.balance_history import balance_history

CLASS_ORDER = ["Assets", "Equity", "Liabilities"]


def canon_class(c) -> str:
    """Source mixes Class ('Asset') and Type ('Assets') labels — normalize to one set."""
    s = (c or "").strip().lower()
    if s.startswith("asset"):
        return "Assets"
    if s.startswith("liab"):
        return "Liabilities"
    if s.startswith("equit"):
        return "Equity"
    return (c or "").strip() or "(unclassified)"


def month_rows(snapshots: list[dict]) -> list[dict]:
    """Starting / Ending / Max balance per (Class, Account) from one month's Snapshots in
    date order. Class falls back to the coarse Type; the first row's Institution is kept."""
    acc: dict = {}
    for d in snapshots:
        key = (d.get("Class") or d.get("Type"), d.get("Account"))
        bal = d.get("Balance")
        cur = acc.get(key)
        if cur is None:
            acc[key] = {"cls": canon_class(key[0]), "account": key[1],
                        "institution": d.get("Institution"),
                        "starting": bal, "ending": bal, "maxb": bal}
        else:
            cur["ending"] = bal
            cur["maxb"] = max(cur["maxb"], bal)
    return [{**r, "starting": round(r["starting"], 2), "ending": round(r["ending"], 2),
             "maxb": round(r["maxb"], 2)} for r in acc.values()]


def summarize(rows: list[dict]) -> dict:
    """{assets, liabilities, net_worth} from month_rows(): assets = ending Assets + Equity,
    liabilities = |ending Liabilities|, net worth = assets − liabilities."""
    def ending(cls):
        return sum(r["ending"] for r in rows if r["cls"] == cls)
    assets = ending("Assets") + ending("Equity")
    liabilities = abs(ending("Liabilities"))
    return {"assets": round(assets, 2), "liabilities": round(liabilities, 2),
            "net_worth": round(assets - liabilities, 2)}


def _ym(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def prev_month(ym: str) -> str:
    """'2026-01' → '2025-12'."""
    y, m = int(ym[:4]), int(ym[5:7])
    return _ym(y - 1, 12) if m == 1 else _ym(y, m - 1)


def net_worth_at(ym: str) -> dict | None:
    """Net worth as of the end of month `ym` ('YYYY-MM'): {assets, liabilities, net_worth,
    as_of, exact}. A month with no Snapshots falls back to the latest earlier month that has
    some (`as_of` names it, `exact` is False); None when nothing precedes it."""
    target = (int(ym[:4]), int(ym[5:7]))
    months = balance_history.months()                   # newest first
    chosen = next((m for m in months if m <= target), None)
    if chosen is None:
        return None
    rows = month_rows(balance_history.in_month(*chosen))
    return {**summarize(rows), "as_of": _ym(*chosen), "exact": chosen == target}


def net_worth_delta(ym: str) -> dict | None:
    """{value, as_of, prev, prev_as_of, delta} — the month's net worth against the month
    before the one it was measured in. `delta` is None when there is no earlier month."""
    cur = net_worth_at(ym)
    if cur is None:
        return None
    prev = net_worth_at(prev_month(cur["as_of"]))
    return {
        "value": cur["net_worth"], "as_of": cur["as_of"], "exact": cur["exact"],
        "prev": prev["net_worth"] if prev else None,
        "prev_as_of": prev["as_of"] if prev else None,
        "delta": round(cur["net_worth"] - prev["net_worth"], 2) if prev else None,
    }
