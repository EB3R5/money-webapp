"""View seam helpers — the shared way operations report a 4xx to the browser, and the
small adapters every view uses.

A DomainError raised anywhere in an operation (a bad field, a duplicate item, an in-use
delete) is mapped to a JSON 4xx in one place, app.middleware.DomainErrorMiddleware.
GridError (grid) and LookupError (lookups) are both just DomainError.

Helpers: read_json (tolerant JSON body), json (JsonResponse that refuses a NaN rather than
emitting a token JSON.parse rejects), page (render a Jinja template with optional
route-owned headers), redirect (303 by default: the forms expect it), GET / POST (405 on
the wrong method)."""

import json as _json

from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST


class DomainError(Exception):
    """A 4xx an operation reports back to the caller. `extra` rides along in the JSON body
    (e.g. the in-use count the delete guard surfaces)."""

    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra


def jsonable_dict(value):
    """Datetimes to ISO strings, recursively — for JSONResponse over store rows."""
    from datetime import date, datetime
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable_dict(v) for v in value]
    return value


GET = require_http_methods(["GET", "HEAD"])
POST = require_POST


def read_json(request) -> dict:
    """Best-effort JSON body; empty dict when there isn't one (or it is not an object)."""
    try:
        body = _json.loads(request.body or b"")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def json(data, status: int = 200) -> JsonResponse:
    """JSON-encode a result (any JSON value, not only a dict). A NaN raises rather than
    emitting a token JSON.parse rejects."""
    return JsonResponse(data, safe=False, status=status,
                        json_dumps_params={"ensure_ascii": False, "allow_nan": False})


def page(request, name: str, context: dict | None = None, *, status: int = 200,
         headers: dict | None = None) -> HttpResponse:
    """Render a Jinja template. `headers` are stamped on the response — the clip popup's own
    CSP, the document raw route's frame headers (security.ROUTE_OWNED_HEADERS)."""
    response = render(request, name, context or {}, status=status)
    for k, v in (headers or {}).items():
        response[k] = v
    return response


def redirect(url: str, status: int = 303) -> HttpResponseRedirect:
    response = HttpResponseRedirect(url)
    response.status_code = status
    return response
