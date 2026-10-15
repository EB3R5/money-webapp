"""The feed running on its own and on demand: job registration gated on the Access URL,
the startup catch-up rule, the non-blocking lock (409), the status endpoint, and the
Activity page's run history, warnings, and Sync now form."""

import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app import config
from app.simplefin import schedule as sched
from app.simplefin import sync as sf
from app.simplefin.client import SimpleFinClient
from app.store.sync_cursors import sync_cursors
from app.store.sync_runs import sync_runs
from tests.test_simplefin_sync import ACCESS, NOW, payload


@pytest.fixture(autouse=True)
def _one_chunk(monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 90)


# --- registration + catch-up rule ----------------------------------------------------

def test_jobs_registered_only_with_access_url(monkeypatch):
    s = BackgroundScheduler()
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", "")
    assert sched.register_jobs(s, now=NOW) == [] and s.get_jobs() == []
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", ACCESS)
    monkeypatch.setattr(config, "SYNC_INTERVAL_HOURS", 6)
    monkeypatch.setattr(config, "SYNC_CRON_MINUTE", 17)
    ids = sched.register_jobs(s, now=NOW)
    assert ids == [sched.JOB_ID, sched.CATCHUP_JOB_ID]
    cron = s.get_job(sched.JOB_ID)
    assert cron.coalesce is True and cron.max_instances == 1 and cron.misfire_grace_time == 3600
    assert "hour='*/6'" in str(cron.trigger) and "minute='17'" in str(cron.trigger)
    catchup = s.get_job(sched.CATCHUP_JOB_ID)
    assert catchup.trigger.run_date == NOW + timedelta(seconds=sched.CATCHUP_DELAY_S)


def test_should_catch_up_when_no_cursor_or_stale(store_db, monkeypatch):
    monkeypatch.setattr(config, "SYNC_STALE_HOURS", 12)
    assert sched.should_catch_up(NOW) is True                       # no Cursor yet
    sync_cursors.insert({"_id": "simplefin", "window_end": NOW, "last_success_at": NOW - timedelta(hours=1)})
    assert sched.should_catch_up(NOW) is False                      # fresh
    sync_cursors.update("simplefin", {"last_success_at": NOW - timedelta(hours=13)})
    assert sched.should_catch_up(NOW) is True                       # stale


def test_startup_catchup_runs_only_when_stale(store_db, monkeypatch):
    calls = []
    def fake_run(**kw):
        calls.append(kw["trigger"])
        return sf.SyncSummary(status="ok")
    monkeypatch.setattr(sf, "run_sync", fake_run)
    sched.startup_catchup()                                          # no cursor → runs
    assert calls == ["startup"]
    sync_cursors.insert({"_id": "simplefin", "window_end": datetime.now(UTC),
                               "last_success_at": datetime.now(UTC)})
    sched.startup_catchup()                                          # fresh → skipped
    assert calls == ["startup"]
    sched.scheduled_sync()
    assert calls == ["startup", "scheduler"]


# --- lock, endpoint, status -----------------------------------------------------------

def slow_client(gate: threading.Event, entered: threading.Event | None = None):
    """A client whose fetch blocks until `gate` is set (and flags `entered` first)."""
    def handler(r: httpx.Request):
        if entered is not None:
            entered.set()
        assert gate.wait(timeout=10)
        return httpx.Response(200, json=payload())
    return SimpleFinClient(ACCESS, transport=httpx.MockTransport(handler))


class _Run(threading.Thread):
    """run_sync in a background thread (its own connection, like a scheduler job)."""

    def __init__(self, **kw):
        super().__init__(daemon=True)
        self.kw, self.result, self.error = kw, None, None

    def run(self):
        try:
            self.result = sf.run_sync(**self.kw)
        except BaseException as e:        # pragma: no cover - surfaces in join()
            self.error = e

    def join_result(self):
        self.join(timeout=10)
        if self.error:
            raise self.error
        return self.result


def _start_blocked_run(**kw):
    gate, entered = threading.Event(), threading.Event()
    t = _Run(client=slow_client(gate, entered), **kw)
    t.start()
    assert entered.wait(timeout=10)       # the run holds the lock and sits in the fetch
    return gate, t


def test_second_run_is_refused_while_one_is_in_progress(store_db):
    gate, t = _start_blocked_run(now=NOW)
    assert sf.is_running() is True
    with pytest.raises(sf.SyncBusy):
        sf.run_sync(client=slow_client(gate), now=NOW)
    gate.set()
    s = t.join_result()
    assert s.status == "ok" and sf.is_running() is False
    assert sync_runs.count() == 1


def test_endpoint_runs_and_409s_when_busy(store_client, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", ACCESS)
    gate, t = _start_blocked_run(now=NOW)
    r = store_client.post("/sync/simplefin")
    assert r.status_code == 409 and r.json()["ok"] is False
    r = store_client.post("/sync/simplefin?next=/activity", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/activity?sync=busy"
    gate.set()
    t.join_result()
    # not busy any more: a real run through the endpoint (mocked transport via the module client)
    monkeypatch.setattr(sf, "SimpleFinClient", lambda url: slow_client(gate))
    r = store_client.post("/sync/simplefin")
    body = r.json()
    assert r.status_code == 200 and body["ok"] and body["status"] == "ok" and body["trigger"] == "manual"
    r = store_client.post("/sync/simplefin?next=/activity", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/activity?sync=ok"
    assert (store_client.post("/sync/simplefin?since=June")).status_code == 400


def test_status_endpoint(store_client, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", ACCESS)
    d = (store_client.get("/sync/simplefin/status")).json()
    assert d == {"configured": True, "running": False, "last_run": None, "cursor": None,
                 "requests_used_today": 0, "budget": config.SIMPLEFIN_DAILY_BUDGET}
    gate = threading.Event(); gate.set()
    s = sf.run_sync(client=slow_client(gate), now=datetime.now(UTC))
    d = (store_client.get("/sync/simplefin/status")).json()
    assert d["last_run"]["_id"] == s.run_id and d["last_run"]["status"] == "ok"
    assert isinstance(d["cursor"]["window_end"], str) and d["requests_used_today"] == 1


# --- activity page ---------------------------------------------------------------------

def test_activity_lists_runs_escapes_warnings_and_has_the_form(store_client, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", ACCESS)
    body = payload(errlist=[{"code": "con.refresh", "msg": "<script>alert(1)</script> bank says hi", "conn_id": "c1"}])
    c = SimpleFinClient(ACCESS, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    s = sf.run_sync(client=c, now=datetime.now(UTC), trigger="manual")
    assert s.status == "partial"
    r = store_client.get("/activity?sync=partial")
    html = r.text
    assert r.status_code == 200
    assert 'action="/sync/simplefin?next=/activity"' in html and 'id="sf-sync-now"' in html
    assert "pill-partial" in html and "manual" in html                    # the run row
    assert "&lt;script&gt;alert(1)&lt;/script&gt; bank says hi" in html   # escaped warning
    assert "<script>alert(1)</script>" not in html
    assert "last request: <strong>partial</strong>" in html
    assert "requests today 1/" in html
    assert '<th class="num">Rules</th><th class="num">ML</th>' in html   # the run's categorization counts


# --- the other process ------------------------------------------------------------------

def test_a_running_row_from_another_process_counts_as_busy(store_db):
    """The web and jobs containers share the database, not a lock: a recent `sync_runs`
    row still marked running means busy; a stale one (a crashed run) does not."""
    from datetime import timedelta
    from app.store.sync_runs import sync_runs
    now = datetime.now(UTC)
    assert sf.is_running(now) is False
    sync_runs.insert({"_id": "run_other", "feed": sf.FEED, "started_at": now - timedelta(minutes=5),
                      "status": "running", "trigger": "scheduler"})
    assert sf.is_running(now) is True
    with pytest.raises(sf.SyncBusy):
        sf.run_sync(client=slow_client(threading.Event()), now=now)
    sync_runs.update("run_other", {"started_at": now - timedelta(hours=2)})
    assert sf.is_running(now) is False
    sync_runs.update("run_other", {"status": "ok"})
    assert sf.is_running(now) is False
