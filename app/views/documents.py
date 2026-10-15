"""Document pages and the document JSON surface (ADR-0016). `/documents/{id}` renders one
document by kind; the API side is edit/rename, delete, the raw bytes (with their own frame
headers for HTML and PDF), and the Markdown preview. The parent-scoped upload and note routes live on the CardCollection that owns the
parent (app/card_collection.py), behind its `documents_enabled` flag."""

from urllib.parse import quote

from django.http import HttpResponse
from django.urls import path

from .. import documents, web
from ..middleware import error_page
from ..web import DomainError


def _flag(request, name: str) -> bool:
    try:
        return bool(int(request.GET.get(name, 0)))
    except ValueError:
        return False


@web.GET
def document_page(request, doc_id: str):
    try:
        d = documents.get(doc_id)
    except DomainError:
        return error_page(request, 404, "Document not found")
    ctx = documents.page_context(d)
    return web.page(request, "document.html", {"doc": ctx, "edit": _flag(request, "edit") and ctx["editable"]})


@web.GET
def document_raw(request, doc_id: str):
    data, ct, name, embed = documents.raw(doc_id)          # a DomainError is the JSON 4xx
    disposition = "inline" if embed != "download" and not _flag(request, "download") else "attachment"
    ascii_name = name.encode("ascii", "ignore").decode().replace('"', "") or "document"
    headers = {"Content-Disposition":
               f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}'}
    if embed == "html":
        # Belt and braces with the page's sandboxed <iframe>: this CSP sandboxes the response
        # itself, so even opened directly the uploaded page has an opaque origin — scripts may
        # run but cannot read the session cookie or call the API. Framing by our own pages only.
        headers["Content-Security-Policy"] = "sandbox allow-scripts allow-forms allow-popups"
        headers["X-Frame-Options"] = "SAMEORIGIN"
    elif embed == "pdf":
        # The browser's own viewer, framed by our pages only. No sandbox: Chrome refuses to run
        # its PDF viewer inside a sandboxed frame.
        headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        headers["X-Frame-Options"] = "SAMEORIGIN"
    return HttpResponse(data, content_type=ct, headers=headers)


@web.POST
def render_preview(request):
    body = web.read_json(request)
    return web.json({"html": documents.render_markdown(body.get("body") or "")})


@web.POST
def update_document(request, doc_id: str):
    body = web.read_json(request)
    return web.json(documents.update(doc_id, body.get("updates") or {}))


@web.POST
def delete_document(request, doc_id: str):
    return web.json(documents.delete(doc_id))


# `render` is a fixed segment: it must precede the `<doc_id>` route.
urlpatterns = [
    path("documents/<str:doc_id>", document_page),
    path("api/documents/<str:doc_id>/raw", document_raw),
    path("api/documents/render", render_preview),
    path("api/documents/<str:doc_id>", update_document),
    path("api/documents/<str:doc_id>/delete", delete_document),
]
