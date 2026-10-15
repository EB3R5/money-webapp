"""Kits — the Kit page (`/kits`, `/kits/{id}`) and the membership route, over a
CardCollection that supplies the Kit's own CRUD, photos and Documents (plan D5–D9, ADR-0018).

The collection renders `kits.html` through the engine's page seam instead of the card board:
a sidebar of every Kit and one Kit in detail — cover hero, how-to, the photo grid of every
member, and the transfer list that edits membership through POST /api/kits/{id}/members.
The edit modal is the shared partial driven by card-editor.js; the Kit's identity is its
row id (no KIT-###)."""

from django.urls import path

from .. import kits as domain
from .. import web
from ..card_collection import CardCollection, CardField
from ..middleware import error_page
from ..store.deletions import deletions
from ..store.kit_members import kit_members
from ..store.kits import kits

NAME_REQUIRED = "a Kit needs a name"


def _require_name(doc, body):
    """fan_out: a Kit is created with a Name or not at all."""
    if not (doc.get("Name") or "").strip():
        return web.json({"ok": False, "error": NAME_REQUIRED}, 400)
    return None


def _keep_name(doc_id, update):
    """before_update: the Name may change but never blank out."""
    if "Name" in update and not (update.get("Name") or "").strip():
        return NAME_REQUIRED
    return None


def _audit_members_then_documents(ids):
    """Deleting a Kit: its memberships are audited as `kit_members` rows before the database
    cascades them away; its Documents cascade as on every board."""
    rows = kit_members.list({"kit_id": ids})
    if rows:
        deletions.log(kit_members.table, rows)
    from .. import documents
    documents.delete_for_parents(kits.table, ids)


def _first_kit_id(docs):
    """The Kit `/kits` shows: the first by name, case-insensitive."""
    if not docs:
        return None
    return sorted(docs, key=lambda d: ((d.get("Name") or "").lower(), d["_id"]))[0]["_id"]


def _page_context(request, docs, sections):
    """What kits.html needs beyond the board's context: the sidebar, the current Kit in
    full, and the catalog the transfer list picks from."""
    cat = domain.catalog()
    by_kit = domain.memberships_by_kit()
    counts = domain.kit_counts(by_kit)
    by_id = {d["_id"]: d for d in docs}
    sidebar = []
    for d in sorted(docs, key=lambda d: ((d.get("Name") or "").lower(), d["_id"])):
        members = domain.resolve(by_kit.get(d["_id"], []), cat)
        sidebar.append({"id": d["_id"], "name": d.get("Name") or "(unnamed)",
                        "count": len(members), "cover": domain.cover(d, members)})
    kit_id = getattr(request, "kit_id", None) or _first_kit_id(docs)
    current = domain.view(by_id[kit_id], by_kit.get(kit_id, []), cat) if kit_id in by_id else None
    avail = domain.available(cat, current["member_keys"], counts) if current else []
    return {"kits": sidebar, "current": current, "available": avail,
            "catalog": [{**m, "in_kits": counts.get(m["key"], 0)} for m in cat.values()]}


_kits = CardCollection(
    slug="kits",
    store=kits,
    id_field="_id",
    title_field="Name",
    group_by="_all",                 # no such field: one section holding every Kit
    unclassified_label="Kits",
    heading="Kits",
    noun="kits",
    item_noun="kit",
    fields=[CardField("Name"), CardField("Description"), CardField("How_To", "textarea")],
    amount=lambda d: None,
    numeric_mode="coerce_float",     # blank text → NULL, as the boards store it
    can_create=True,
    can_delete=True,
    fan_out=_require_name,
    before_update=_keep_name,
    delete_hook=_audit_members_then_documents,
    images_enabled=True,
    documents_enabled=True,
    template="kits.html",
    page_context=_page_context,
)

@web.GET
def kit_page(request, kit_id: str):
    """/kits/<id>: one Kit; an unknown id is a 404 page, not an empty state."""
    if kits.get(kit_id) is None:
        return error_page(request, 404, "No such Kit.")
    request.kit_id = kit_id
    return _kits.page(request)


@web.POST
def members(request, kit_id: str):
    """POST {add: [member keys], remove: [member keys]}: removes first, then appends the adds
    at the end in the order given. Unknown keys and keys that name no row are ignored.
    Returns the Kit's members as the page renders them, its stats and cover."""
    kit = kits.get(kit_id)
    if kit is None:
        return web.json({"ok": False, "error": "not found"}, 404)
    body = web.read_json(request)
    cat = domain.catalog()
    removed = kit_members.remove(kit_id, domain.valid_keys(body.get("remove"), cat))
    added = kit_members.add(kit_id, domain.valid_keys(body.get("add"), cat))
    rows = kit_members.list_for_kit(kit_id)
    v = domain.view(_kits.serialize(kit), rows, cat)
    counts = domain.kit_counts(domain.memberships_by_kit())
    return web.json({"ok": True, "added": added, "removed": removed,
                     "members": v["members"], "member_keys": v["member_keys"],
                     "stats": v["stats"], "cover": v["cover"],
                     "available": domain.available(cat, v["member_keys"], counts)})


# /kits/<kit_id> beside the engine's /kits; /api/kits/<kit_id>/members is two segments, so it
# never shadows the engine's /api/kits/<doc_id> update route.
urlpatterns = [
    *_kits.urlpatterns(),
    path("kits/<str:kit_id>", kit_page),
    path("api/kits/<str:kit_id>/members", members),
]
