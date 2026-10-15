"""Categories — CRUD the lookup tables that feed the app's category dropdowns, organized by
their Group → item → derived-fields hierarchy. One page, a button per registered context
(Ledger Categories, Balances, …); the heavy lifting (the cascade onto transactions /
balanceHistory) lives in app/lookups.py. This file is the thin HTTP adapter: pick a
context by slug and call the lookup operations; a LookupError is a DomainError and so a
JSON 4xx (app.middleware)."""

from django.urls import path

from .. import lookups, web
from ..lookups import CONTEXTS, get_context


@web.GET
def categories_page(request):
    contexts = [{"slug": c.slug, "label": c.label, "section_field": c.section_field,
                 "item_field": c.item_field, "columns": c.columns,
                 "cascade_fields": list(c.cascade_fields), "item_noun": c.item_noun,
                 "target_noun": c.target_noun}
                for c in CONTEXTS.values()]
    return web.page(request, "categories.html", {"contexts": contexts})


@web.GET
def sections(request, ctx: str):
    c = get_context(ctx)
    return web.json({"sections": lookups.list_sections(c), "options": lookups.field_options(c)})


@web.GET
def items(request, ctx: str):
    c = get_context(ctx)
    return web.json({"items": lookups.list_items(c, request.GET.get("section", ""))})


def _unknown(ctx: str):
    return web.json({"ok": False, "error": f"unknown context '{ctx}'"}, 404)


@web.POST
def add_row(request, ctx: str):
    body = web.read_json(request)
    return web.json(lookups.add_item(get_context(ctx), body)) if ctx in CONTEXTS else _unknown(ctx)


@web.POST
def update_row(request, ctx: str):
    body = web.read_json(request)
    return web.json(lookups.update_item(get_context(ctx), body)) if ctx in CONTEXTS else _unknown(ctx)


@web.POST
def delete_row(request, ctx: str):
    body = web.read_json(request)
    return web.json(lookups.delete_item(get_context(ctx), body)) if ctx in CONTEXTS else _unknown(ctx)


urlpatterns = [
    path("categories", categories_page),
    path("api/categories/<str:ctx>/sections", sections),
    path("api/categories/<str:ctx>/row", add_row),
    path("api/categories/<str:ctx>/update", update_row),
    path("api/categories/<str:ctx>/delete", delete_row),
    path("api/categories/<str:ctx>", items),
]
