"""Software — a CardCollection adapter (see CONTEXT.md, ADR-0017).

Software you have, use, or are trialing, as cards grouped by Status (or Kind, or
Category), backed by the `software` table. Same deep module as Accounts and Inventory;
this file declares the software-specific config (SW-### minting, the monthly cost as the
card amount, the read-only `_meta` overlay for stored-only facts, the import strip) and
appends the one route the engine doesn't cover: /facts, where the clipper (and a later
"refresh from source") writes the registry-owned fields the modal never touches. The
import endpoint lives in software_sync.py and the clipper in software_clip.py; both must
be registered before this router (see main.py)."""

from datetime import UTC, datetime

from django.urls import path

from .. import web
from ..card_collection import CardCollection, CardField
from ..software_clip import route
from ..software_item import (ACTIVE_STATUSES, FIELDS, KINDS, SEARCH_FIELDS, STATUSES,
                             entry_sort_key, from_wire, monthly_cost as _monthly_cost,
                             source_key, subtitle as _subtitle)
from ..store.software import software

# Stored-only facts surfaced read-only in the modal (serialize() emits form fields only).
_META_KEYS = ("Source_Key", "Homepage", "Repo_URL", "License_Id", "Bundle_Id", "Version_Latest",
              "Stars", "Topics", "Archived", "Install_Locations", "_refreshed_at", "_import_status")

# What /facts may write from a registry (never Status / Cost / Notes / Category / Item_Name).
REMOTE_FIELDS = ["Version_Latest", "Stars", "Topics", "Archived", "License_Id", "Homepage",
                 "Repo_URL", "Vendor", "Bundle_Id"]


def _filter(request, row: dict) -> bool:
    """Status buckets: active (default: using + trialing + installed_unused) /
    cancelled / uninstalled / all."""
    status = request.GET.get("status", "active")
    if status == "all":
        return True
    if status == "active":
        return row.get("Status") in ACTIVE_STATUSES
    return row.get("Status") == status


def _on_create(doc):
    """A hand-added item is something you have. Link → Source_Key when the URL routes
    to a registry (so a later facts fetch / import can find it)."""
    doc.setdefault("Status", "using")
    doc.setdefault("Kind", "app")
    doc.setdefault("License_Type", "free")
    doc.setdefault("Billing_Cadence", "none")
    doc.setdefault("Currency", "USD")
    doc.setdefault("_src", "manual")
    if not doc.get("Source_Key"):
        r = route(doc.get("Link") or "")
        if r:
            doc["Source_Key"] = source_key(*r)


def _taken(sk, doc_id=None):
    """The SW-### already holding this Source_Key (other than doc_id), else None."""
    if not sk:
        return None
    other = software.one({"Source_Key": sk})
    if other is None or other["_id"] == doc_id:
        return None
    return other.get("SW_ID") or other["_id"]


def _mint_sw_id(doc, body):
    """fan_out: assign the next SW-### (the app is the sole minter) and refuse a
    Source_Key another card already owns (the partial unique index would 500)."""
    holder = _taken(doc.get("Source_Key"))
    if holder:
        return web.json({"ok": False, "error": f"Source_Key already used by {holder}"}, 400)
    doc["SW_ID"] = f"SW-{software.max_sw_num() + 1:03d}"
    return None


def _veto_source_key(doc_id, update):
    holder = _taken(update.get("Source_Key"), doc_id)
    return f"Source_Key already used by {holder}" if holder else None


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def meta_of(row: dict) -> dict:
    """The stored-only facts of one row, in the shape software.js renders read-only."""
    return {
        "source_key": row.get("Source_Key"), "homepage": row.get("Homepage"),
        "repo_url": row.get("Repo_URL"), "license_id": row.get("License_Id"),
        "bundle_id": row.get("Bundle_Id"), "version_latest": row.get("Version_Latest"),
        "stars": row.get("Stars"), "topics": row.get("Topics") or [], "archived": row.get("Archived"),
        "install_locations": row.get("Install_Locations") or [],
        "refreshed_at": _iso(row.get("_refreshed_at")),
        "automatic_status": bool(row.get("_import_status")) and row.get("_import_status") == row.get("Status"),
    }


def _overlay(docs):
    """`_group` (Category or Uncategorized) for the group-by toggle, plus `_meta`: the
    stored-only facts the modal shows read-only. The subtitle is recomputed with
    Version_Latest so the card can hint `vA → vB`."""
    rows = {r["_id"]: r for r in software.list({"_id": [d["_id"] for d in docs]})} if docs else {}
    for d in docs:
        d["_group"] = d.get("Category") or "Uncategorized"
        m = rows.get(d["_id"], {})
        d["_meta"] = meta_of(m)
        d["_subtitle"] = _subtitle({**d, "Version_Latest": m.get("Version_Latest")})


def _import_banner(request):
    """The import strip is always offered (it is how an exporter's run gets in: CSRF
    covers every POST, so a script cannot curl the endpoint — the browser can)."""
    return {"show": True}


_software = CardCollection(
    slug="software",
    store=software,
    id_field="SW_ID",
    title_field="Item_Name",
    group_by="Status",
    heading="Software",
    noun="software · ≈$/mo subscriptions",
    item_noun="software item",
    fields=[CardField(name, kind, options) for name, kind, options in FIELDS],
    amount=_monthly_cost,                            # card amount + section/board totals = monthly cost
    subtitle=_subtitle,
    entry_sort=entry_sort_key,
    numeric_mode="coerce_float",
    section_order=STATUSES,
    unclassified_label="using",
    filter=_filter,
    statuses=["active", "cancelled", "uninstalled", "all"],
    default_status="active",
    group_options={"status": ("Status", STATUSES), "kind": ("Kind", KINDS),
                   "category": ("_group", None)},
    default_group="status",
    show_grand=True,
    can_create=True,
    can_delete=True,
    on_create=_on_create,
    fan_out=_mint_sw_id,
    before_update=_veto_source_key,
    page_overlay=_overlay,
    banner=_import_banner,
    banner_template="software_import_strip.html",
    link_field="Link",
    images_enabled=True,
    documents_enabled=True,
    kits_enabled=True,               # the Kits chips in the modal (ADR-0018)
    search_fields=SEARCH_FIELDS,
)

def set_facts(doc_id: str, wire: dict) -> dict:
    """Write registry-owned fields from a wire dict onto a row: REMOTE_FIELDS when they
    differ, Description only when the row has none, Source_Key only when the row has none
    (an identity never silently changes). Status, Cost, Notes, Category and Item_Name are
    never touched. {"ok", "updated": [...]} or {"ok": False, "error"}."""
    doc = software.get(doc_id)
    if doc is None:
        return {"ok": False, "error": "not found", "status": 404}
    fields = from_wire(wire or {})
    changes = {k: fields[k] for k in REMOTE_FIELDS if k in fields and doc.get(k) != fields[k]}
    if fields.get("Description") and not doc.get("Description"):
        changes["Description"] = fields["Description"]
    sk = fields.get("Source_Key")
    if sk and not doc.get("Source_Key"):
        holder = _taken(sk, doc_id)
        if holder:
            return {"ok": False, "error": f"Source_Key already used by {holder}", "status": 400}
        changes["Source_Key"] = sk
    software.update(doc_id, {**changes, "_refreshed_at": datetime.now(UTC)})
    return {"ok": True, "updated": sorted(changes)}


@web.POST
def _facts(request, doc_id: str):
    res = set_facts(doc_id, web.read_json(request))
    status = res.pop("status", 200)
    return web.json(res, status)


# /<doc_id>/facts is two segments — no clash with the engine's /<doc_id> update route.
urlpatterns = [
    *_software.urlpatterns(),
    path("api/software/<str:doc_id>/facts", _facts),
]
