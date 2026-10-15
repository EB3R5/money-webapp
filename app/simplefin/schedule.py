"""When the SimpleFIN feed runs on its own.

A cron job every SYNC_INTERVAL_HOURS at SYNC_CRON_MINUTE (coalesce missed firings into
one, never two at once, an hour of grace after a sleep), registered only when the Access
URL is set; plus a one-shot catch-up 20 s after start that runs only when there is no
Cursor yet or the last success is older than SYNC_STALE_HOURS — the box reboots often,
and a fresh boot should not burn a request if the last run was recent."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from apscheduler.triggers.cron import CronTrigger

from .. import config
from ..store.sync_cursors import sync_cursors
from . import sync as sf

log = logging.getLogger("money.simplefin")

JOB_ID = "simplefin_sync"
CATCHUP_JOB_ID = "simplefin_startup_catchup"
CATCHUP_DELAY_S = 20


def should_catch_up(now: Optional[datetime] = None) -> bool:
    """No Cursor yet, or the last success is older than the stale threshold."""
    now = now or datetime.now(UTC)
    cur = sync_cursors.get(sf.FEED)
    last = cur.get("last_success_at") if cur else None
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return last < now - timedelta(hours=config.SYNC_STALE_HOURS)


def scheduled_sync() -> None:
    try:
        s = sf.run_sync(trigger="scheduler")
        log.info("SimpleFIN scheduled sync: %s (new %s, updated %s, requests %s)",
                 s.status, s.txns_new, s.txns_updated, s.requests_used)
    except sf.SyncBusy:
        log.warning("SimpleFIN scheduled sync skipped: a run is in progress")


def startup_catchup() -> None:
    if not should_catch_up():
        log.info("SimpleFIN startup catch-up not needed")
        return
    try:
        s = sf.run_sync(trigger="startup")
        log.info("SimpleFIN startup catch-up: %s", s.status)
    except sf.SyncBusy:
        log.warning("SimpleFIN startup catch-up skipped: a run is in progress")


def register_jobs(scheduler, *, now: Optional[datetime] = None) -> list[str]:
    """Add the feed's jobs to the scheduler when the feed is configured. Returns the ids."""
    if not config.SIMPLEFIN_ACCESS_URL:
        log.info("SimpleFIN feed not configured; no sync jobs registered")
        return []
    now = now or datetime.now(UTC)
    scheduler.add_job(
        scheduled_sync, CronTrigger(hour=f"*/{config.SYNC_INTERVAL_HOURS}", minute=config.SYNC_CRON_MINUTE),
        id=JOB_ID, replace_existing=True, coalesce=True, max_instances=1, misfire_grace_time=3600)
    scheduler.add_job(startup_catchup, "date", run_date=now + timedelta(seconds=CATCHUP_DELAY_S),
                      id=CATCHUP_JOB_ID, replace_existing=True, misfire_grace_time=3600)
    return [JOB_ID, CATCHUP_JOB_ID]
