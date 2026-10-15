"""Tax page — Config + Category Mapping + Tax History stored; Income/Deductions, Tax
Calculations and Quarterly Estimates computed live from the shared transactions. Thin HTTP
adapter over app/tax.py through the shared guard()/read_body() seam."""

from datetime import UTC, datetime

from django.urls import path

from .. import rollup, tax, web


def _int(request, name: str, default=None):
    """An optional integer query parameter; anything unparsable is the default."""
    v = request.GET.get(name)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _pick_year(year, all_years, cfg_year):
    if year in all_years:
        return year
    if cfg_year in all_years:
        return cfg_year
    now = datetime.now(UTC).year
    return now if now in all_years else (all_years[0] if all_years else now)


@web.GET
def tax_page(request):
    year = _int(request, "year")
    tax.sync_mapping()
    cfg = tax.get_config()
    all_years = rollup.years()
    sel = _pick_year(year, all_years, cfg["tax_year"])
    rows = tax.income_deductions(sel)
    return web.page(request, "tax.html", {
        "config": cfg, "years": all_years, "year": sel,
        "calc": tax.calc_full_tax(sel, cfg),
        "income": rows["income"], "deductions": rows["deductions"],
        "quarterly": tax.quarterly_estimates(sel, cfg),
        "history": tax.list_history(),
        "mapping": tax.list_mapping(),
        "roles": list(tax.TAX_ROLES),
        "filing_statuses": list(tax.FILING_STATUSES),
    })


@web.GET
def calc(request):
    cfg = tax.get_config()
    all_years = rollup.years()
    sel = _pick_year(_int(request, "year"), all_years, cfg["tax_year"])
    return web.json({"calc": tax.calc_full_tax(sel, cfg),
                     "quarterly": tax.quarterly_estimates(sel, cfg), "year": sel})


@web.POST
def config(request):
    return web.json(tax.set_config(web.read_json(request)))


@web.POST
def sync(request):
    return web.json(tax.sync_mapping())


@web.POST
def mapping(request):
    return web.json(tax.set_mapping(web.read_json(request)))


@web.POST
def add_history(request):
    return web.json(tax.add_history(web.read_json(request)))


@web.POST
def delete_history(request):
    return web.json(tax.delete_history(web.read_json(request)))


urlpatterns = [
    path("tax", tax_page),
    path("api/tax/calc", calc),
    path("api/tax/config", config),
    path("api/tax/sync", sync),
    path("api/tax/mapping", mapping),
    path("api/tax/history", add_history),
    path("api/tax/history/delete", delete_history),
]
