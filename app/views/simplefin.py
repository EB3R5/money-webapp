"""SimpleFIN sync endpoints: trigger a run and read its status. SimpleFIN is the app's only
live feed (ADR-0015). The scheduled runs live in the jobs process (`manage.py run_jobs`);
this is the Activity page's Sync now button and the status JSON."""

from datetime import date

from django.urls import path
from django.utils.http import url_has_allowed_host_and_scheme

from .. import web
from ..simplefin import sync as sf
from ..web import jsonable_dict


def _next(request):
    nxt = request.GET.get("next") or ""
    ok = nxt.startswith("/") and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return nxt if ok else None


@web.POST
def trigger(request):
    """Run the feed now. JSON summary, or 409 while a run is in progress (here or in the
    jobs process). With `next` (a local path, e.g. the Activity page's form), redirect
    there with `?sync=<status>`."""
    dry_run = request.GET.get("dry_run", "").lower() in ("1", "true", "yes")
    since = request.GET.get("since") or None
    nxt = _next(request)
    try:
        since_d = date.fromisoformat(since) if since else None
    except ValueError:
        return web.json({"ok": False, "error": "since must be YYYY-MM-DD"}, 400)
    try:
        summary = sf.run_sync(trigger="manual", dry_run=dry_run, since=since_d)
    except sf.SyncBusy:
        if nxt:
            return web.redirect(f"{nxt}?sync=busy")
        return web.json({"ok": False, "error": "a sync is already running"}, 409)
    if nxt:
        return web.redirect(f"{nxt}?sync={summary.status}")
    return web.json({"ok": summary.status in ("ok", "partial"), **summary.as_dict()})


@web.GET
def status(request):
    return web.json(jsonable_dict(sf.status()))


urlpatterns = [
    path("sync/simplefin", trigger),
    path("sync/simplefin/status", status),
]
