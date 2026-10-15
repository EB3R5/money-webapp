"""Data page — browse ANY app-owned table through one AG Grid (`/data`), for rows that
have no page of their own. Tables and columns come from the live schema; the block
datasource lives in app/store/datatable.py. Internal and credential tables are hidden
(404 everywhere); only `autocat` is editable, through its own Store's dirty-diff update;
every other table answers 403 on update — including `deletions`, browsable for recovery."""

from django.urls import path

from .. import web
from ..grid import Grid
from ..store.autocat import autocat
from ..store.datatable import EDITABLE, datatable
from ..web import DomainError

# The one editable table, through the same Grid the typed pages use (coercion by kind).
_editors = {"autocat": Grid(store=autocat, columns=autocat.api_keys())}


def _unknown():
    return web.json({"error": "unknown table"}, 404)


@web.GET
def data_page(request):
    return web.page(request, "data.html", {"tables": datatable.tables()})


@web.GET
def data_columns(request, table: str):
    if not datatable.exists(table):
        return _unknown()
    cols = datatable.columns(table)
    return web.json({"columns": [c["key"] for c in cols], "editable": table in EDITABLE})


@web.POST
def data_rows(request, table: str):
    if not datatable.exists(table):
        return _unknown()
    return web.json(datatable.block(table, web.read_json(request)))


@web.GET
def data_doc(request, table: str, row_id: str):
    if not datatable.exists(table):
        return _unknown()
    d = datatable.get(table, row_id)
    if d is None:
        return web.json({"error": "not found"}, 404)
    return web.json({"doc": d})


@web.POST
def data_update(request, table: str):
    if not datatable.exists(table):
        return web.json({"ok": False, "error": "unknown table"}, 404)
    editor = _editors.get(table)
    if editor is None:
        return web.json({"ok": False, "error": f"{table} is read-only here"}, 403)
    try:
        return web.json(editor.update_field(web.read_json(request)))
    except DomainError as e:
        return web.json({"ok": False, "error": e.message}, e.status)


urlpatterns = [
    path("data", data_page),
    path("api/data/<str:table>/columns", data_columns),
    path("api/data/<str:table>/rows", data_rows),
    path("api/data/<str:table>/doc/<str:row_id>", data_doc),
    path("api/data/<str:table>/update", data_update),
]
