"""Jinja filters the Planning templates use (ADR-0021): money and percent formatting, month
names. Installed on the shared environment by config/jinja2.py; pure functions, so they
have no view to live in."""

import calendar


def money(v, signed: bool = False) -> str:
    """$1,234 — whole dollars; signed=True prefixes + / − for deltas."""
    if v is None:
        return "—"
    v = float(v)
    sign = ("+" if v > 0 else "−" if v < 0 else "") if signed else ("−" if v < 0 else "")
    return f"{sign}${abs(v):,.0f}"


def pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%".replace("-", "−")


def month_abbr(m) -> str:
    return calendar.month_abbr[int(m)]


def month_short(ym) -> str:
    return f"{calendar.month_abbr[int(ym[5:7])]} {ym[2:4]}" if ym else "—"


def datetime_short(v) -> str:
    return v.strftime("%d %b %H:%M") if hasattr(v, "strftime") else str(v or "")[:16].replace("T", " ")


FILTERS = {"money": money, "pct": pct, "month_abbr": month_abbr, "month_short": month_short,
           "datetime_short": datetime_short}
