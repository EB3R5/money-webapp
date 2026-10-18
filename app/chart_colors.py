"""Chart colors: the six series colors every ECharts view draws from, chosen per user on the
Dashboard's collapsible panel or Settings → Appearance and kept on the user's Profile
(`chart_colors`, overrides only). The ledger's money-in green and money-out red are not
among them: those are the pad's ink, not the charts'.

Each page render puts the user's six on `<html>` as `--chart-*` tokens (base.html, from the
`chart_colors` context processor); `chart-theme.js` reads them from there, so the theme's
series palette and the explicit colors in dashboard.js, metrics.js and planning-forecast.js
all follow."""

import re

from .models import Profile

# (role, label, default) — in the order the ECharts theme's series palette uses them
ROLES = (
    ("net", "Net line, top categories", "#4f6b8c"),
    ("income", "Income bars", "#2f6b4f"),
    ("spend", "Spend bars", "#a4302a"),
    ("s4", "Series 4", "#8a6414"),
    ("s5", "Series 5", "#5b3fa6"),
    ("s6", "Series 6", "#5c6670"),
)
DEFAULTS = {role: default for role, _, default in ROLES}
_HEX = re.compile(r"^#[0-9a-f]{6}$")


def normalise(raw: dict) -> dict:
    """The overrides worth storing from a submitted mapping: known roles only, lower-case
    six-digit hex, defaults dropped. Raises ValueError naming the first bad value."""
    out = {}
    for role, _, default in ROLES:
        value = str(raw.get(role, "") or "").strip().lower()
        if not value or value == default:
            continue
        if not _HEX.match(value):
            raise ValueError(f"{role}: {value!r} is not a color like #4f6b8c")
        out[role] = value
    return out


def for_user(user) -> dict:
    """role → hex for every role: the user's overrides over the defaults. Anonymous (the
    login page, tests without a session) gets the defaults."""
    colors = dict(DEFAULTS)
    if getattr(user, "is_authenticated", False):
        stored = Profile.objects.filter(user_id=user.pk).values_list("chart_colors", flat=True).first() or {}
        colors.update({k: v for k, v in stored.items() if k in colors and _HEX.match(str(v))})
    return colors


def save(user, raw: dict) -> dict:
    """Store the overrides in `raw` (validated with `normalise`) and return the full mapping."""
    overrides = normalise(raw)
    Profile.objects.update_or_create(user=user, defaults={"chart_colors": overrides})
    return for_user(user)


def rows(current: dict) -> list[dict]:
    """What the panel renders from a `for_user` mapping: one row per role with its label,
    current value and default."""
    return [{"role": role, "label": label, "value": current[role], "default": default} for role, label, default in ROLES]
