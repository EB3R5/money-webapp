"""`manage.py run_jobs` (app/management/commands/run_jobs.py): the feed's jobs plus the
daily session clean-up on one blocking scheduler, registered without starting it; with no
Access URL only the clean-up remains, so the container idles instead of exiting."""

from apscheduler.schedulers.blocking import BlockingScheduler
from django.contrib.sessions.models import Session
from django.utils import timezone

from app import config
from app.management.commands import run_jobs
from app.simplefin import schedule as sched


def test_build_registers_the_feed_jobs_and_the_session_cleanup(monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", "https://u:p@bridge.test/simplefin")
    s = run_jobs.build(BlockingScheduler())
    ids = {j.id for j in s.get_jobs()}
    assert ids == {sched.JOB_ID, sched.CATCHUP_JOB_ID, run_jobs.CLEARSESSIONS_JOB_ID}
    assert s.get_job(run_jobs.CLEARSESSIONS_JOB_ID).misfire_grace_time == 3600
    assert not s.running


def test_without_a_feed_only_the_cleanup_is_registered(monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", "")
    s = run_jobs.build(BlockingScheduler())
    assert [j.id for j in s.get_jobs()] == [run_jobs.CLEARSESSIONS_JOB_ID]


def test_clear_sessions_removes_expired_rows(store_db):
    Session.objects.create(session_key="expired0000000000000000000000000", session_data="x",
                           expire_date=timezone.now() - timezone.timedelta(days=1))
    Session.objects.create(session_key="live000000000000000000000000000x", session_data="x",
                           expire_date=timezone.now() + timezone.timedelta(days=1))
    run_jobs.clear_sessions()
    assert list(Session.objects.values_list("session_key", flat=True)) == ["live000000000000000000000000000x"]
