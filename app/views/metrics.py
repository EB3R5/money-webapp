"""Metrics hub — one page, a section per financial-health domain. Only the Savings section
is live (Credit / Tax / Health are placeholders); see app/savings.py for the computation.
This file is the thin HTTP adapter: render the
shell and serve the savings JSON + mapping/config/goal CRUD through the shared guard() seam."""

from datetime import UTC, datetime

from django.urls import path

from .. import rollup, savings, web


def _int(request, name: str, default=None):
    """An optional integer query parameter; anything unparsable is the default."""
    v = request.GET.get(name)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _pick_year(year, all_years):
    """Selected year: the requested one if present, else the current year if it has data,
    else the most recent year (mirrors reports.pnl)."""
    if year in all_years:
        return year
    now = datetime.now(UTC).year
    return now if now in all_years else (all_years[0] if all_years else now)


@web.GET
def metrics_page(request):
    year = _int(request, "year")
    savings.sync_mapping()                 # seed roles for any new categories on load
    cfg = savings.get_savings_config()
    all_years = rollup.years()
    sel = _pick_year(year, all_years)
    rate = savings.savings_rate_by_month(sel, cfg)
    return web.page(request, "metrics.html", {
        "config": cfg,
        "years": all_years,
        "year": sel,
        "summary": rate["summary"],
        "rows": rate["rows"],
        "goals": savings.list_goals(sel, cfg),
        "account_names": sorted(savings.account_balances()),
        "mapping": savings.list_mapping(),
        "roles": list(savings.ROLES),
    })


@web.GET
def savings_data(request):
    year = _int(request, "year")

    def payload():
        cfg = savings.get_savings_config()
        all_years = rollup.years()
        sel = _pick_year(year, all_years)
        rate = savings.savings_rate_by_month(sel, cfg)
        return {"config": cfg, "year": sel, "years": all_years,
                "summary": rate["summary"], "rows": rate["rows"],
                "goals": savings.list_goals(sel, cfg)}
    return web.json(payload())


@web.GET
def savings_projections(request):
    return web.json(savings.projections(_pick_year(_int(request, "year"), rollup.years())))


@web.GET
def savings_scenarios(request):
    return web.json(savings.rate_scenarios(_pick_year(_int(request, "year"), rollup.years())))


@web.POST
def savings_config(request):
    return web.json(savings.set_savings_config(web.read_json(request)))


@web.POST
def savings_sync(request):
    return web.json(savings.sync_mapping())


@web.POST
def savings_mapping(request):
    return web.json(savings.set_mapping_role(web.read_json(request)))


@web.POST
def add_goal(request):
    return web.json(savings.add_goal(web.read_json(request)))


@web.POST
def update_goal(request):
    return web.json(savings.update_goal(web.read_json(request)))


@web.POST
def delete_goal(request):
    return web.json(savings.delete_goal(web.read_json(request)))


urlpatterns = [
    path("metrics", metrics_page),
    path("api/metrics/savings", savings_data),
    path("api/metrics/savings/projections", savings_projections),
    path("api/metrics/savings/scenarios", savings_scenarios),
    path("api/metrics/savings/config", savings_config),
    path("api/metrics/savings/sync", savings_sync),
    path("api/metrics/savings/mapping", savings_mapping),
    path("api/metrics/savings/goals", add_goal),
    path("api/metrics/savings/goals/update", update_goal),
    path("api/metrics/savings/goals/delete", delete_goal),
]
