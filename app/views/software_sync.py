"""POST /api/software/import — the endpoint a software exporter's run is posted to
(from the board's import strip; see app/software_import.py for the rules).

Registered BEFORE the software board's patterns: /api/software/import is one segment past
the slug and would otherwise be swallowed by /api/software/<doc_id>."""

import json

from django.urls import path

from .. import web
from ..software_import import apply_run


@web.POST
def software_import(request):
    try:
        body = json.loads(request.body or b"")
    except ValueError:
        return web.json({"status": "error", "error": "invalid JSON"}, 400)
    res = apply_run(body)
    return web.json(res, 200 if res["status"] == "ok" else 400)


urlpatterns = [
    path("api/software/import", software_import),
]
