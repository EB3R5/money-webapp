"""Planning section (ADR-0021): the Month, Notebook, Planner, Income, Year plan, Calendar and
Projected P&L pages, plus the Journal entry and flows API under /api/planning. Numbers come
from app.planning; this module only routes and renders."""

from django.urls import path
from django.utils.http import url_has_allowed_host_and_scheme

from .. import expected_flows, future_purchases, planning, reconcile, web
from ..budgets import current_month
from ..middleware import error_page
from ..web import DomainError, jsonable_dict

# The money / pct / month filters these templates use live in app/jinja_filters.py and are
# installed on the shared environment by config/jinja2.py.


def _int(request, name: str, default=None):
    v = request.GET.get(name)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _next(request):
    """The page to return to after a form POST (?next=): a local path or nothing."""
    nxt = request.GET.get("next") or ""
    ok = nxt.startswith("/") and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return nxt if ok else None


# --- pages ------------------------------------------------------------------------------

@web.GET
def month_redirect(request):
    return web.redirect(f"/planning/month/{current_month()}")


@web.GET
def month_page(request, ym: str):
    """The 'figures first' layout: stat tiles, Budget-vs-Actual, the Journal entry panel."""
    if not planning.is_month(ym):
        return error_page(request, 404, "No such month.")
    facts = planning.month_facts(ym)
    entry = planning.get_entry(ym)
    prompts = planning.month_prompts(facts, entry["body"] if entry else "")
    return web.page(request, "planning_month.html",
                    {"f": facts, "entry": jsonable_dict(entry), "open": planning.is_open(ym),
                     "preview": planning.figures_from_facts(facts), "prompts": prompts})


@web.GET
def planner_redirect(request):
    return web.redirect(f"/planning/planner/{current_month()[:4]}")


@web.GET
def planner_page(request, year: str):
    """The Planner: the year strip, expected income, sinking funds, and the current
    month's Journal entry as a drawer."""
    if not planning.is_year(year):
        return error_page(request, 404, "No such year.")
    y = planning.year_facts(year)
    ym = y["current_month"]
    facts = planning.month_facts(ym)
    entry = planning.get_entry(ym)
    prompts = planning.month_prompts(facts, entry["body"] if entry else "")
    return web.page(request, "planning_planner.html",
                    {"y": y, "f": facts, "entry": jsonable_dict(entry), "open": planning.is_open(ym),
                     "preview": planning.figures_from_facts(facts), "prompts": prompts})


@web.GET
def forecast_api(request):
    """The checking forecast as JSON for the Planner's chart; ?days= sets the horizon."""
    return web.json(planning.forecast(days=_int(request, "days", planning.FORECAST_DAYS)))


@web.GET
def income_page(request):
    """The Income sources: the typed rows, the add/edit form, the detected series left."""
    merged = expected_flows.merged_sources()
    return web.page(request, "planning_income.html", {
        "q": request.GET.get("q", ""),
        "sources": expected_flows.list_sources(),
        "detected": [s for s in merged if s["origin"] == expected_flows.DETECTED],
        "income_categories": expected_flows.income_categories(),
        "cadences": expected_flows.CADENCES,
    })


@web.POST
def income_add(request):
    return web.json(expected_flows.add_source(web.read_json(request)))


@web.POST
def income_update(request):
    return web.json(expected_flows.update_source(web.read_json(request)))


@web.POST
def income_delete(request):
    return web.json(expected_flows.delete_source(web.read_json(request)))


# --- Year plan (ADR-0023) -----------------------------------------------------------------------

def _plan_context(request) -> dict:
    plan = jsonable_dict(planning.year_plan(start=request.GET.get("start") or None))   # datetimes in last_pull / dates in funds
    return {"p": plan, "sync": request.GET.get("sync"), "q": request.GET.get("q", ""),
            "reconciled": request.GET.get("reconcile")}


@web.GET
def year_page(request):
    """The Year plan: twelve months of planned spend as a timeline, the detail card, the
    affordability list, the shelf and the add form."""
    return web.page(request, "planning_year.html", _plan_context(request))


@web.GET
def year_api(request):
    return web.json(jsonable_dict(planning.year_plan(start=request.GET.get("start") or None)))


@web.GET
def calendar_page(request):
    """The Calendar: twelve month cards, the shelf of unplaced planned spend (click one, then
    a month), and the funds panel — the same year_plan() facts as the Year plan."""
    return web.page(request, "planning_calendar.html", _plan_context(request))


@web.POST
def flow_add(request):
    body = web.read_json(request)
    return web.json(expected_flows.add_flow({**body, "kind": "expense"}))


@web.POST
def flow_update(request):
    return web.json(expected_flows.update_flow(web.read_json(request)))


@web.POST
def flow_delete(request):
    return web.json(expected_flows.delete_flow(web.read_json(request)))


@web.POST
def flow_done(request, flow_id: str):
    return web.json(expected_flows.mark_done(flow_id))


@web.POST
def sync_future_purchases(request):
    """Run one Pull. With ?next= (the page forms) redirect there with ?sync=<status>;
    otherwise answer JSON. 503 when FUTURE_PURCHASES_URL is unset."""
    nxt = _next(request)
    try:
        result = future_purchases.pull(trigger="manual")
    except DomainError as e:
        if nxt:
            return web.redirect(f"{nxt}?sync=not-configured")
        return web.json({"ok": False, "error": e.message}, e.status)
    if nxt:
        return web.redirect(f"{nxt}?sync={result['status']}")
    return web.json(result)


@web.GET
def projected_page(request):
    """The Projected P&L: the current month actual and eleven projected columns, planned
    spend as a row per Group, net after savings."""
    return web.page(request, "planning_projected.html",
                    {"x": jsonable_dict(planning.projected_pnl(start=request.GET.get("start") or None)),
                     "q": request.GET.get("q", "")})


@web.POST
def reconcile_planned(request):
    """Match placed planned spend to ledger transactions (#181). With ?next= redirect there
    with ?reconcile=<matched count>; otherwise answer JSON."""
    result = reconcile.reconcile()
    nxt = _next(request)
    if nxt:
        return web.redirect(f"{nxt}?reconcile={len(result['matched'])}")
    return web.json(result)


# --- Journal entry API ------------------------------------------------------------------

def _entry_payload(period: str) -> dict:
    return {"ok": True, "entry": jsonable_dict(planning.get_entry(period))}


@web.POST
def save_entry(request, period: str):
    """Upsert the body; the first save after the period ends freezes the figures. Body: {"body": "..."}."""
    body = web.read_json(request)
    planning.save_entry(period, body.get("body", ""))
    return web.json(_entry_payload(period))


@web.POST
def refreeze_entry(request, period: str):
    planning.refreeze(period)
    return web.json(_entry_payload(period))


@web.POST
def delete_entry(request, period: str):
    return web.json(planning.delete_entry(period))


# --- Notebook page (D7) ------------------------------------------------------------------

@web.GET
def notebook_redirect(request):
    return web.redirect(f"/planning/notebook/{current_month()}")


@web.GET
def notebook_page(request, period: str):
    """The entry as a document: rendered Markdown with Figure blocks, the month rail, the
    open prompts; ?edit=1 is Write mode (textarea + live preview)."""
    if not planning.is_period(period):
        return error_page(request, 404, "No such month or year.")
    view = jsonable_dict(planning.notebook_view(period))
    return web.page(request, "planning_notebook.html", {"v": view, "edit": bool(_int(request, "edit", 0))})


urlpatterns = [
    path("planning", month_redirect),
    path("planning/month", month_redirect),
    path("planning/month/<str:ym>", month_page),
    path("planning/planner", planner_redirect),
    path("planning/planner/<str:year>", planner_page),
    path("api/planning/forecast", forecast_api),
    path("planning/income", income_page),
    path("api/planning/income", income_add),
    path("api/planning/income/update", income_update),
    path("api/planning/income/delete", income_delete),
    path("planning/year", year_page),
    path("api/planning/year", year_api),
    path("planning/calendar", calendar_page),
    path("api/planning/flows", flow_add),
    path("api/planning/flows/update", flow_update),
    path("api/planning/flows/delete", flow_delete),
    path("api/planning/flows/<str:flow_id>/done", flow_done),
    path("api/planning/sync/future-purchases", sync_future_purchases),
    path("planning/projected", projected_page),
    path("api/planning/reconcile", reconcile_planned),
    path("api/planning/entry/<str:period>", save_entry),
    path("api/planning/entry/<str:period>/refreeze", refreeze_entry),
    path("api/planning/entry/<str:period>/delete", delete_entry),
    path("planning/notebook", notebook_redirect),
    path("planning/notebook/<str:period>", notebook_page),
]
