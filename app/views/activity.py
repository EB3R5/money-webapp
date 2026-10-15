"""App Activity — a status page (and JSON endpoint) over app/data_health.py, plus the
SimpleFIN feed's run history and a "Sync now" form. The page renders the latest health
snapshot for a human; /api/health returns the same snapshot as JSON for other apps to
poll. Both recompute and persist the snapshot to app_health/current."""

from datetime import UTC, datetime

from django.urls import path

from .. import web
from ..config import FUTURE_PURCHASES_URL
from ..data_health import compute_health, jsonable
from ..store.sync_runs import sync_runs

RUNS_SHOWN = 30


@web.GET
def activity_page(request):
    health = compute_health()
    runs = sync_runs.recent(limit=RUNS_SHOWN)
    fp_last = sync_runs.recent("future-purchases", limit=1)
    latest_errlist = next((r.get("errlist") or [] for r in runs if r.get("errlist")), [])
    return web.page(request, "activity.html", {
        "h": health, "now": datetime.now(UTC), "runs": runs, "latest_errlist": latest_errlist,
        "sync_result": request.GET.get("sync"),
        "fp_configured": bool(FUTURE_PURCHASES_URL), "fp_last": fp_last[0] if fp_last else None,
    })


@web.GET
def health_json(request):
    """Latest health snapshot, JSON-safe — the status surface for external apps."""
    return web.json(jsonable(compute_health()))


urlpatterns = [
    path("activity", activity_page),
    path("api/health", health_json),
]
