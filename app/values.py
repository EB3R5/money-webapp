"""Shared user-input parsers — the one place manual-entry operations coerce money and
date strings, reporting bad input as a DomainError.

Metrics, tax, and credit each grew their own copy and they had drifted: metrics rejected
"1,200" while tax and credit accepted it, and only credit tolerated a datetime-ish date
string. The strict parsers live here now; the only per-caller choice is what blank input
means (tax config fields read as 0.0, credit registry fields as None, a goal's
target_amount is required).

The lenient display/cleaning parsers (card_collection.num0, autocat._num,
ml_model._amount) are a different contract — garbage → default, never an error — and
deliberately stay where they are.
"""

from datetime import datetime

from .web import DomainError

REQUIRED = object()  # sentinel: blank input is an error, not a default


def parse_amount(v, field: str, *, blank=REQUIRED) -> float | None:
    """Money-ish input ("1,200", "$35", 12.5) → float rounded to cents. `blank` is what
    None/"" becomes — a default (0.0, None) or REQUIRED to reject it."""
    if v in (None, ""):
        if blank is REQUIRED:
            raise DomainError(f"{field} must be a number")
        return blank
    try:
        return round(float(str(v).replace(",", "").replace("$", "").strip()), 2)
    except (TypeError, ValueError):
        raise DomainError(f"{field} must be a number")


def parse_date(v, field: str = "date") -> str | None:
    """Optional date input → "YYYY-MM-DD", or None when blank. A datetime-ish string is
    accepted by its first 10 chars."""
    if not v:
        return None
    s = str(v).strip()[:10]
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise DomainError(f"{field} must be YYYY-MM-DD")
    return s
