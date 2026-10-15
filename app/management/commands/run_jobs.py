"""`manage.py run_jobs`: the scheduler, out of the web process (ADR-0024). A blocking
APScheduler with the feed's jobs from app/simplefin/schedule.py (the cron run and the
20-second catch-up, only when the Access URL is set) plus a daily clean-up of expired
sessions. Runs as its own container beside the web one, on the same data volume; with no
feed configured it idles so the container stays up. SIGTERM stops it cleanly."""

from __future__ import annotations

import logging
import signal

from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management import call_command
from django.core.management.base import BaseCommand

from app.simplefin import schedule as simplefin_schedule
from app.store import database

log = logging.getLogger("money.jobs")

CLEARSESSIONS_JOB_ID = "clearsessions"


def clear_sessions() -> None:
    call_command("clearsessions", verbosity=0)
    log.info("expired sessions cleared")


def build(scheduler: BlockingScheduler | None = None) -> BlockingScheduler:
    """A scheduler with every job registered and nothing started (testable)."""
    scheduler = scheduler or BlockingScheduler()
    simplefin_schedule.register_jobs(scheduler)
    scheduler.add_job(clear_sessions, "cron", hour=3, minute=7, id=CLEARSESSIONS_JOB_ID,
                      replace_existing=True, misfire_grace_time=3600)
    return scheduler


class Command(BaseCommand):
    help = "Run the scheduled jobs (SimpleFIN sync, session clean-up) until stopped."

    def handle(self, *args, **options):
        database.init()
        scheduler = build()

        def stop(signum, frame):
            log.info("stopping on signal %s", signum)
            scheduler.shutdown(wait=False)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        log.info("jobs: %s", ", ".join(j.id for j in scheduler.get_jobs()))
        scheduler.start()
