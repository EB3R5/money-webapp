"""Software — the schema for the software board (see CONTEXT.md, ADR-0017).

Software the user has, uses, or is trialing: an app, CLI, library, editor extension,
SaaS or OS package. Distinct from a Future Purchase (not yet owned) and a Recurring
Purchase (a consumable restocked on a cadence): its identity is a package key
(`Source_Key`), it is installed on hosts (`Install_Locations`), and its cost is a billing
cadence. This module owns the field list, the wire contract the exporter / clipper /
importer share, and the derivations the adapter wires in: the monthly cost (card
amount + board total), the subtitle, the within-section order, and the import
status rule."""

import re

from .card_collection import to_float as to_cost

TABLE = "software"

STATUSES = ["using", "trialing", "installed_unused", "cancelled", "uninstalled"]
ACTIVE_STATUSES = STATUSES[:3]           # the default board view
KINDS = ["app", "cli", "library", "extension", "saas", "os_package"]
LICENSE_TYPES = ["free", "oss", "perpetual", "subscription", "trial"]
CADENCES = ["none", "monthly", "yearly", "one_time"]

# (field, kind, options) in display order. This is also the modal's write whitelist —
# facts the importer/fetchers own (Install_Locations, Stars, Version_Latest, …) are
# deliberately NOT here so a modal save never coerces or nulls them (see STORED_ONLY).
FIELDS = [
    ("Item_Name", "text", None),
    ("Status", "select", STATUSES),
    ("Kind", "select", KINDS),
    ("Vendor", "text", None),
    ("Category", "text", None),
    ("License_Type", "select", LICENSE_TYPES),
    ("Billing_Cadence", "select", CADENCES),
    ("Cost", "number", None),                 # per cadence period; one_time = purchase price
    ("Version_Installed", "text", None),
    ("Link", "text", None),                   # the ↗ target: store / repo / homepage page
    ("Source_Key", "text", None),             # editable so a hand-made card can be linked to a fetcher
    ("Merchant_Match", "text", None),         # reserved for a later ledger link
    ("Description", "textarea", None),
    ("Notes", "textarea", None),
]
FIELD_NAMES = [name for name, _k, _o in FIELDS]

# Stored on the doc but never in the form (written by import / clip / refresh only).
STORED_ONLY = ["SW_ID", "Homepage", "Repo_URL", "License_Id", "Bundle_Id", "Currency",
               "Version_Latest", "Stars", "Topics", "Archived", "Install_Locations",
               "Last_Used", "Use_Count", "_import_status", "_refreshed_at"]

SEARCH_FIELDS = ["Item_Name", "SW_ID", "Status", "Kind", "Vendor", "Category", "License_Type",
                 "Source_Key", "Description", "Notes"]

# The wire contract (snake_case) shared by the exporter, the clipper's fetchers, the
# import endpoint and any future agent. `status`, `install_locations` and `image_url`
# are deliberately absent: the caller decides those, they are never blindly copied.
WIRE = {
    "name": "Item_Name", "vendor": "Vendor", "description": "Description",
    "homepage": "Homepage", "repo_url": "Repo_URL", "link": "Link",
    "license_type": "License_Type", "license_id": "License_Id",
    "billing_cadence": "Billing_Cadence", "cost": "Cost", "currency": "Currency",
    "merchant_match": "Merchant_Match", "version_installed": "Version_Installed",
    "version_latest": "Version_Latest", "bundle_id": "Bundle_Id",
    "last_used": "Last_Used", "use_count": "Use_Count", "stars": "Stars", "topics": "Topics",
    "archived": "Archived", "category": "Category", "notes": "Notes", "kind": "Kind",
    "source_key": "Source_Key",
}
_ENUMS = {"Kind": KINDS, "License_Type": LICENSE_TYPES, "Billing_Cadence": CADENCES}

# Who owns which field on a re-import / refresh:
#   OVERWRITE — facts the source is the authority on; replaced whenever they differ.
#   FILL      — filled only when the doc has no value yet (the user may have curated them).
#   everything else (Item_Name, Status, Cost, Currency, Billing_Cadence, Merchant_Match,
#   Notes) is set on insert only and never touched by the importer.
OVERWRITE_FIELDS = ["Version_Installed", "Install_Locations", "Version_Latest", "Stars", "Topics",
                    "Archived", "Bundle_Id", "Repo_URL", "Homepage", "License_Id"]
FILL_FIELDS = ["Description", "License_Type", "Kind", "Vendor", "Link", "Category"]


def from_wire(rec: dict) -> dict:
    """Wire record -> stored fields. Drops None/"" (an update never nulls a field —
    the sync.py rule), drops invalid enum values, coerces cost, and derives Link from
    homepage/repo_url when the record has no explicit link."""
    out = {}
    for wk, field in WIRE.items():
        v = rec.get(wk)
        if v is None or v == "":
            continue
        if field == "Cost":
            v = to_cost(v)
            if v is None:
                continue
        elif field in _ENUMS:
            v = str(v).strip().lower()
            if v not in _ENUMS[field]:
                continue
        elif field in ("Stars", "Use_Count"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
        elif field == "Topics":
            if not isinstance(v, list):
                continue
            v = [str(t) for t in v]
        elif field == "Archived":
            v = bool(v)
        elif isinstance(v, str):
            v = v.strip()
            if not v:
                continue
        out[field] = v
    if "Link" not in out:
        link = out.get("Homepage") or out.get("Repo_URL")
        if link:
            out["Link"] = link
    return out


def monthly_cost(d: dict):
    """The card amount + section/board totals: what this software costs per month.
    monthly → Cost; yearly → Cost/12; one-time, none, or free/oss → None (renders '—',
    contributes 0). So the board total is the subscription run-rate."""
    cost = d.get("Cost")
    if not isinstance(cost, (int, float)):
        return None
    if d.get("License_Type") in ("free", "oss"):
        return None
    cad = d.get("Billing_Cadence")
    if cad == "monthly":
        return round(float(cost), 2)
    if cad == "yearly":
        return round(cost / 12, 2)
    return None


def _fmt_cost(cost, cad):
    if cad == "monthly":
        return f"${cost:,.0f}/mo"
    if cad == "yearly":
        return f"${cost:,.0f}/yr"
    if cad == "one_time":
        return f"${cost:,.0f} once"
    return None


def norm_version(v):
    """'v15.2.0' / '15.2.0-1' (pacman pkgrel) / '1:2.3-4' (epoch) -> '15.2.0' / '2.3', for
    comparing an installed version with a registry's latest. None stays None."""
    if v is None:
        return None
    s = str(v).strip()
    s = re.sub(r"^\d+:", "", s)              # epoch
    s = re.sub(r"^[vV](?=\d)", "", s)        # leading v
    s = re.sub(r"-\d+$", "", s)              # pkgrel
    return s


def same_version(a, b) -> bool:
    return norm_version(a) == norm_version(b)


def subtitle(d: dict):
    """Kind · cost per cadence · version (with `vA → vB` when a newer version is known;
    pacman's pkgrel and a tag's leading v don't count as a difference)."""
    bits = []
    if d.get("Kind"):
        bits.append(d["Kind"])
    cost = d.get("Cost")
    if isinstance(cost, (int, float)):
        s = _fmt_cost(cost, d.get("Billing_Cadence"))
        if s:
            bits.append(s)
    vi, vl = d.get("Version_Installed"), d.get("Version_Latest")
    if vi and vl and not same_version(vi, vl):
        bits.append(f"v{vi} → v{vl}")
    elif vi or vl:
        bits.append(f"v{vi or vl}")
    return " · ".join(bits) or None


def entry_sort_key(d: dict):
    """Within a section: highest monthly cost first, then name."""
    return (-(monthly_cost(d) or 0), (d.get("Item_Name") or "").lower())


def source_key(source: str, key: str) -> str:
    return f"{source}:{key}"


def split_source_key(sk):
    """'npm:@scope/name' -> ('npm', '@scope/name'); 'brew:cask:x' -> ('brew', 'cask:x').
    None when the key has no source prefix."""
    if not isinstance(sk, str) or ":" not in sk:
        return None
    source, key = sk.split(":", 1)
    source, key = source.strip(), key.strip()
    return (source, key) if source and key else None


def status_for_import(existing, has_locations: bool, hinted=None):
    """The importer's Status rule. A new item is `using` when the export shows it
    installed, else the exporter's hint (or `trialing`). An existing item's Status is
    *automatic* only while it still equals `_import_status` (the last value the importer
    set) — once the user changed it by hand, the importer leaves it alone (None)."""
    if existing is None:
        if has_locations:
            return "using"
        return hinted if hinted in STATUSES else "trialing"
    if existing.get("Status") != existing.get("_import_status"):
        return None
    if not has_locations and existing.get("Status") in ("using", "installed_unused"):
        return "uninstalled"
    if has_locations and existing.get("Status") == "uninstalled":
        return "using"
    return None
