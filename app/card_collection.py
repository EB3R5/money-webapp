"""CardCollection — one deep module for the card-grid + editable-modal pattern.

Accounts and Inventory were the same dance copied twice (server *and* client):
serialize → group into sections with totals → click a card → open a modal →
dirty-diff save → reflect back onto the card. This module owns that dance once.
Each page is a thin adapter that declares its store, grouping field, editable
fields, and how to derive a card's amount + subtitle; the quirks (status filter,
float coercion, derived Value, create/delete, photos) ride on config, not copied code.

Photos are Blobs (ADR-0020, app/store/blobs.py): the row keeps the entry list in its
`_images` JSON column and the image route serves a photo id straight from `blobs`, so a
blob and the row that names it commit in the same request. Documents (ADR-0016) are rows of their own in `documents`,
keyed by this collection's table + the row id; the page ships each item's list (no bodies)
and the parent-scoped upload / note routes ride here behind `documents_enabled`.

Kits (ADR-0018) are rows of `kit_members` naming this collection's rows as members; with
`kits_enabled` the page ships each row's Kits (`_kits`) for the modal's read-only chips and the
delete cascade removes the memberships beside the documents.

Client mirror: app/static/js/card-editor.js (makeCardEditor).
Shared view:   app/templates/card_collection.html (the modal is the partial _card_modal.html).
A collection may render a page of its own over the same routes: `template` names it and
`page_context` adds to what the template gets (the Kit page, app/views/kits.py).
"""

import secrets
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from typing import Callable, List, Optional

from django.http import HttpRequest, HttpResponse
from django.urls import path

from . import documents, web
from .store.blobs import blobs
from .store.kit_members import kit_members
from .store.base import Store
from .store.deletions import deletions
from .web import DomainError

_KEEP = object()   # build_sections sentinel: "use the configured value"


def to_float(v):
    """'$1,234.56' / '(blank)' → float | None (for coerce_float pages)."""
    if v in (None, "", "—"):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def num0(v):
    """Parse a stringy number, blank/garbage → 0.0 (for derived amounts)."""
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return 0.0


def plain(v):
    """A stored REAL back in the plain form a keep_string page typed it: 2.0 → 2, 2.5 → 2.5."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


@dataclass
class CardField:
    name: str
    kind: str = "text"  # text | number | textarea | select
    options: Optional[List[str]] = None  # for kind == "select"


@dataclass
class CardCollection:
    slug: str                       # URL + API segment, e.g. "accounts"
    store: Store                    # the page's Store
    id_field: str                   # identity field shown in the modal, e.g. "Account ID"
    title_field: str                # card title field
    group_by: str                   # field to section on
    fields: List[CardField]         # editable fields, in form order
    amount: Callable                # (serialized_doc) -> float | None — card amount + section total
    heading: str                    # page <h1>
    noun: str                       # plural noun in the count line, e.g. "accounts"
    subtitle: Callable = lambda d: None
    numeric_mode: str = "coerce_float"          # coerce_float | keep_string
    section_order: Optional[List[str]] = None   # fixed order; None → sort sections by total desc
    unclassified_label: str = "(unclassified)"
    filter: Optional[Callable] = None           # (request, row) -> bool — which rows the page shows
    statuses: Optional[List[str]] = None         # status-filter options for the header
    show_grand: bool = False
    item_noun: str = "item"                      # singular, for the "Add {item_noun}" button
    can_create: bool = False
    can_delete: bool = False
    on_create: Optional[Callable] = None         # (doc) -> None — defaults/id on insert
    fan_out: Optional[Callable] = None           # (doc, body) -> JSONResponse|None.
                                                 # Called after on_create, BEFORE the card insert, so
                                                 # extra writes (detail records, snapshots) land first and
                                                 # a failure never leaves a visible orphan card. May mutate
                                                 # doc; a returned response aborts the create.
    before_update: Optional[Callable] = None     # (doc_id, update) -> error str|None — per-doc veto
    page_overlay: Optional[Callable] = None      # (docs) -> None — mutate serialized docs before
                                                 # sectioning (derive-at-read values)
    banner: Optional[Callable] = None            # (request) -> context dict | None — a page-specific
                                                 # block above the sections (accounts' unlinked feed strip)
    banner_template: Optional[str] = None        # the partial that renders that context
    client_config: dict = dc_field(default_factory=dict)  # page-specific JSON riding window.CARD.extra
    extra_actions: List[dict] = dc_field(default_factory=list)  # [{"id","label","style"?}]
    images_enabled: bool = False                  # per-item photo gallery (files beside the database)
    documents_enabled: bool = False               # per-item documents (notes + files, ADR-0016)
    search_fields: List[str] = dc_field(default_factory=list)  # instant client-side search box
                                                  # over these fields (rule: app/search.py, mirrored in
                                                  # card-editor.js); empty = no box
    delete_hook: Optional[Callable] = None        # (ids) -> None — called after the audit,
                                                  # before the rows go (a cascade). Default: the Documents
                                                  # cascade when documents_enabled, the Kit-membership
                                                  # cascade when kits_enabled (_default_cascade).
    # --- transplanted from future-purchases (the software board, ADR-0017) ---
    entry_sort: Optional[Callable] = None         # (serialized_doc) -> sort key for entries WITHIN a
                                                  # section. Default: by _amount desc.
    link_field: Optional[str] = None              # field holding an http(s) URL; when set the shared
                                                  # template renders a ↗ open-in-new-tab icon on each card
                                                  # (card-editor.js keeps that click from opening the modal).
    default_status: str = "active"                # status-filter default when ?status= is absent.
    group_options: Optional[dict] = None          # {?group= value: (group_by_field, section_order)}. When
                                                  # set the page renders a group-by toggle and build_sections
                                                  # uses the chosen field/order. None → fixed group_by.
    default_group: str = ""                       # default ?group= value when the toggle is present.
    # --- Kits (ADR-0018) and the page seam ---
    kits_enabled: bool = False                    # ship each row's Kits as `_kits` ([{id, name}], by name)
                                                  # for the modal's read-only chips; the delete cascade
                                                  # removes the row's memberships.
    template: str = "card_collection.html"        # the page template; a collection with a page of its own
                                                  # names it here and still gets every route.
    page_context: Optional[Callable] = None       # (request, docs, sections) -> dict merged into the
                                                  # template context (what a page of its own needs beyond
                                                  # the board's: the Kit page's current kit, catalog, …).

    def __post_init__(self):
        if self.documents_enabled:
            documents.register_parent(self.table, store=self.store, title_field=self.title_field,
                                      back_url=f"/{self.slug}", noun=self.item_noun)

    def _default_cascade(self, ids: list) -> None:
        """What a row's deletion takes with it when no delete_hook is given: its Documents
        (when enabled) and its Kit memberships (when enabled). Read at call time, so a flag
        flipped after construction still counts."""
        if self.documents_enabled:
            documents.delete_for_parents(self.table, ids)
        if self.kits_enabled:
            kit_members.delete_for_members(self.table, ids)

    @property
    def table(self) -> str:
        """The backing table's name — the audit label."""
        return self.store.table

    @property
    def editable(self) -> List[str]:
        return [f.name for f in self.fields]

    @property
    def numeric(self) -> List[str]:
        return [f.name for f in self.fields if f.kind == "number"]

    # --- serialization & sectioning -------------------------------------------

    def serialize(self, doc) -> dict:
        out = {"_id": str(doc.get("_id")), self.id_field: doc.get(self.id_field)}
        for f in self.fields:
            v = doc.get(f.name)
            if isinstance(v, datetime):
                v = v.date().isoformat()
            elif isinstance(v, date):
                v = v.isoformat()
            elif self.numeric_mode == "keep_string":
                v = plain(v)
            out[f.name] = v
        out["_amount"] = self.amount(out)
        out["_title"] = out.get(self.title_field)
        out["_subtitle"] = self.subtitle(out)
        if self.images_enabled:
            out["_images"] = doc.get("_images") or []
        return out

    def build_sections(self, docs, group_by=_KEEP, section_order=_KEEP) -> list:
        # group_by/section_order default to the configured values; a group-by toggle
        # (see page()) passes an alternate field + order (section_order=None → by total).
        if group_by is _KEEP:
            group_by = self.group_by
        if section_order is _KEEP:
            section_order = self.section_order
        groups: dict = {}
        for d in docs:
            groups.setdefault(d.get(group_by) or self.unclassified_label, []).append(d)
        sections = []
        for label, items in groups.items():
            if self.entry_sort:
                items.sort(key=self.entry_sort)
            else:
                items.sort(key=lambda i: (i["_amount"] or 0), reverse=True)
            total = round(sum((i["_amount"] or 0) for i in items), 2)
            sections.append({"label": label, "entries": items, "total": total})
        if section_order:
            order = section_order
            sections.sort(key=lambda s: order.index(s["label"]) if s["label"] in order else len(order))
        else:
            sections.sort(key=lambda s: s["total"], reverse=True)
        return sections

    def clean(self, body) -> dict:
        """Whitelist + coerce an inbound payload to stored form (per numeric_mode)."""
        out = {}
        for k, v in body.items():
            if k not in self.editable:
                continue
            if self.numeric_mode == "coerce_float" and k in self.numeric:
                if v in (None, "", "—"):
                    out[k] = None
                else:
                    n = to_float(v)
                    if n is None:
                        raise ValueError(k)
                    out[k] = n
            else:
                if isinstance(v, str):
                    v = v.strip()
                # coerce_float pages null-out empty text; keep_string pages store "".
                out[k] = (v or None) if self.numeric_mode == "coerce_float" else v
        return out

    # --- request handlers ------------------------------------------------------

    def _rows(self, request: HttpRequest) -> list:
        rows = self.store.list()
        if self.filter:
            rows = [d for d in rows if self.filter(request, d)]
        return rows

    def page(self, request: HttpRequest):
        docs = [self.serialize(d) for d in self._rows(request)]
        if self.documents_enabled:
            by_parent = documents.store.list_for_parents(self.table, [d["_id"] for d in docs])
            for d in docs:
                d["_documents"] = [documents.serialize(r) for r in by_parent.get(d["_id"], [])]
        if self.kits_enabled:
            by_member = kit_members.list_for_members(self.table, [d["_id"] for d in docs])
            for d in docs:
                d["_kits"] = by_member.get(f"{self.table}:{d['_id']}", [])
        if self.page_overlay:
            self.page_overlay(docs)
        gkey = request.GET.get("group", self.default_group)
        if self.group_options and gkey in self.group_options:
            gfield, gorder = self.group_options[gkey]
        else:
            gfield, gorder = self.group_by, self.section_order
        sections = self.build_sections(docs, gfield, gorder)
        grand = round(sum(s["total"] for s in sections), 2)
        fields = [{"name": f.name, "kind": f.kind, "options": f.options} for f in self.fields]
        banner = self.banner(request) if self.banner else None
        context = {"cfg": self, "sections": sections, "fields": fields,
                   "count": len(docs), "grand": grand, "banner": banner,
                   "status": request.GET.get("status", self.default_status),
                   "group": gkey, "q": request.GET.get("q", "")}
        if self.page_context:
            context.update(self.page_context(request, docs, sections) or {})
        return web.page(request, self.template, context)

    def update(self, request: HttpRequest, doc_id: str):
        """Persist edited fields for one doc. Body carries ONLY changed fields
        (client sends a dirty-diff), so untouched fields are never wiped."""
        try:
            update = self.clean(web.read_json(request))
        except ValueError as e:
            return web.json({"ok": False, "error": f"{e} not a number"}, 400)
        if not update:
            return web.json({"ok": False, "error": "no editable fields"}, 400)
        if self.before_update:
            err = self.before_update(doc_id, update)
            if err:
                return web.json({"ok": False, "error": err}, 400)
        matched = self.store.update(doc_id, update)
        return web.json({"ok": matched, "matched": 1 if matched else 0})

    def create(self, request: HttpRequest):
        body = web.read_json(request)          # empty body → fully blank doc
        try:
            clean = self.clean(body)
        except ValueError as e:
            return web.json({"ok": False, "error": f"{e} not a number"}, 400)
        doc = {"_id": "man_" + secrets.token_hex(10), **clean}
        if self.on_create:
            self.on_create(doc)
        if self.fan_out:
            err = self.fan_out(doc, body)
            if err is not None:
                return err
        self.store.insert(doc)
        return web.json({"ok": True, "id": doc["_id"], self.id_field: doc.get(self.id_field)})

    def delete(self, request: HttpRequest):
        """Hard-delete by id, after copying the rows to the deletions audit log and running
        the delete hook — the given one, else the default cascade (Documents, Kit
        memberships). Photo and document Blobs stay on purpose (ADR-0005 addendum;
        scripts/prune_blobs.py cleans orphans)."""
        ids = web.read_json(request).get("ids") or []
        if not ids:
            return web.json({"ok": False, "error": "no ids"}, 400)
        docs = [d for d in [self.store.get(i) for i in ids] if d is not None]
        deletions.log(self.store.table, docs)
        if docs:
            (self.delete_hook or self._default_cascade)([d["_id"] for d in docs])
        deleted = self.store.delete_where(_id=[d["_id"] for d in docs]) if docs else 0
        return web.json({"ok": True, "deleted": deleted})

    # --- per-item photos (Blobs, ADR-0020) -------------------------------------

    def _append_image(self, doc_id: str, entry: dict) -> None:
        doc = self.store.get(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        self.store.update(doc_id, {"_images": [*(doc.get("_images") or []), entry]})

    def upload_images(self, doc_id: str, files_: list) -> dict:
        """`files_` are Django UploadedFiles (request.FILES.getlist("files"))."""
        added = []
        for f in files_:
            data = f.read()
            if not data:
                continue
            added.append(blobs.new_photo(data, f.content_type, f.name))
        for entry in added:
            self._append_image(doc_id, entry)
        return {"ok": True, "images": added}

    def attach_image_bytes(self, doc_id: str, data: bytes, content_type: str,
                                 filename: str) -> dict:
        """Attach already-downloaded image bytes (e.g. a product image the inventory
        clipper fetched) to a row — the byte-source sibling of upload_images."""
        entry = blobs.new_photo(data, content_type, filename)
        self._append_image(doc_id, entry)
        return entry

    def get_image(self, file_id: str):
        """(bytes, content type) for a photo id; raises when there is no photo Blob of that
        id. The route stays /api/{slug}/image/{file_id}: the id is the key, and `kind`
        keeps a Document's bytes off the image route."""
        got = blobs.get(file_id, kind="photo")
        if got is None:
            raise FileNotFoundError(file_id)
        return got

    def delete_image(self, doc_id: str, file_id: str) -> dict:
        if not file_id:
            return {"ok": False, "error": "no id"}
        doc = self.store.get(doc_id)
        if doc is None:
            return {"ok": False, "error": "not found"}
        keep = []
        for im in doc.get("_images") or []:
            if im.get("id") == file_id:
                blobs.delete(file_id)   # already gone is fine — still unlink it below
            else:
                keep.append(im)
        self.store.update(doc_id, {"_images": keep})
        return {"ok": True}

    # --- wiring ----------------------------------------------------------------

    def urlpatterns(self) -> list:
        """The Django routes, in the order FastAPI mounted them: the page, the photo and
        document routes, then /row and /delete BEFORE /<doc_id> (a fixed segment registered
        after the parameter route would be shadowed — Django matches by path alone, so a GET
        route one segment past the slug must also precede it)."""
        out = [path(self.slug, web.GET(self.page))]
        if self.images_enabled:
            @web.GET
            def image(request, file_id: str):
                try:
                    data, ct = self.get_image(file_id)
                except Exception:
                    return web.json({"error": "not found"}, 404)
                return HttpResponse(data, content_type=ct, headers={"Cache-Control": "public, max-age=31536000"})

            @web.POST
            def upload(request, doc_id: str):
                return web.json(self.upload_images(doc_id, request.FILES.getlist("files")))

            @web.POST
            def del_image(request, doc_id: str):
                return web.json(self.delete_image(doc_id, web.read_json(request).get("id")))

            out += [path(f"api/{self.slug}/image/<str:file_id>", image),
                    path(f"api/{self.slug}/<str:doc_id>/images", upload),
                    path(f"api/{self.slug}/<str:doc_id>/images/delete", del_image)]
        if self.documents_enabled:
            @web.POST
            def upload_documents(request, doc_id: str):
                added, errors = [], []
                for f in request.FILES.getlist("files"):   # per-file: one bad file never fails the batch
                    try:
                        added.append(documents.add_upload(
                            self.table, doc_id, f.name or "file", f.content_type, f.read()))
                    except DomainError as e:
                        errors.append(e.message)
                return web.json({"ok": not errors, "documents": added, "errors": errors})

            @web.POST
            def new_note(request, doc_id: str):
                body = web.read_json(request)
                return web.json(documents.add_note(self.table, doc_id, body.get("name") or ""))

            out += [path(f"api/{self.slug}/<str:doc_id>/documents", upload_documents),
                    path(f"api/{self.slug}/<str:doc_id>/notes", new_note)]
        if self.can_create:
            out.append(path(f"api/{self.slug}/row", web.POST(self.create)))
        if self.can_delete:
            out.append(path(f"api/{self.slug}/delete", web.POST(self.delete)))
        out.append(path(f"api/{self.slug}/<str:doc_id>", web.POST(self.update)))
        return out
