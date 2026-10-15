"""Financial Health Analysis page — stored input periods + live ratio/composite computation.
Thin HTTP adapter over app/health_metrics.py through the shared guard()/read_body() seam."""

from django.urls import path

from .. import financial_health as hm
from .. import web


@web.GET
def health_page(request):
    current = hm.get_period(request.GET.get("period") or None)
    inputs = current["inputs"] if current else {}
    return web.page(request, "health_metrics.html", {
        "sections": hm.INPUT_SECTIONS,
        "periods": hm.list_periods(),
        "current": current,
        "inputs": inputs,
        "result": hm.compute(inputs),
    })


@web.POST
def save(request):
    return web.json(hm.save_period(web.read_json(request)))


@web.POST
def delete(request):
    return web.json(hm.delete_period(web.read_json(request)))


urlpatterns = [
    path("health-analysis", health_page),
    path("api/health-analysis/save", save),
    path("api/health-analysis/delete", delete),
]
