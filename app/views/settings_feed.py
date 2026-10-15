"""Settings → Feed: the SimpleFIN feed's state on one page — configured or not, today's
request budget, the last run, the next scheduled run, and, when it is not configured, the
exact way to claim an Access URL. The credential itself lives in the environment (ADR-0014)
and never reaches the browser: this page shows that one is set, never what it is."""

from datetime import UTC, datetime

from apscheduler.triggers.cron import CronTrigger
from django.urls import path

from .. import config, web
from ..simplefin import sync as sf
from ..web import jsonable_dict

CLAIM_COMMAND = "python -m app.simplefin.claim --stdin < setup-token.txt"


def next_scheduled_run(now: datetime | None = None) -> datetime | None:
    """When the jobs process fires the next sync (its cron, computed here; the jobs
    container keeps the schedule itself). None when the feed is off."""
    if not config.SIMPLEFIN_ACCESS_URL:
        return None
    now = now or datetime.now(UTC)
    trigger = CronTrigger(hour=f"*/{config.SYNC_INTERVAL_HOURS}", minute=config.SYNC_CRON_MINUTE, timezone=UTC)
    return trigger.get_next_fire_time(None, now)


def feed_context(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    status = jsonable_dict(sf.status(now))
    return {
        "feed": status,
        "remaining": max(0, status["budget"] - status["requests_used_today"]),
        "next_run": next_scheduled_run(now),
        "schedule": {"every_hours": config.SYNC_INTERVAL_HOURS, "minute": config.SYNC_CRON_MINUTE,
                     "stale_hours": config.SYNC_STALE_HOURS, "overlap_days": config.SIMPLEFIN_OVERLAP_DAYS,
                     "lookback_days": config.SIMPLEFIN_INITIAL_LOOKBACK_DAYS,
                     "window_days": config.SIMPLEFIN_MAX_WINDOW_DAYS},
        "claim_command": CLAIM_COMMAND,
    }


@web.GET
def feed_settings_page(request):
    return web.page(request, "settings_feed.html", feed_context())


urlpatterns = [
    path("settings/feed", feed_settings_page),
]
