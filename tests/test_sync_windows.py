"""Window planning, the daily request budget, and the per-chunk cursor
(app/simplefin/sync.py): what makes the feed safe against the Bridge's limits."""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app import config
from app.simplefin import sync as sf
from app.simplefin.client import SimpleFinClient
from app.store.sync_cursors import sync_cursors
from app.store.sync_runs import sync_runs
from app.store.transactions import transactions
from tests.test_simplefin_sync import ACCESS, NOW, POSTED, payload


def _days(w):
    return [round(x.days) for x in w]


# --- plan_windows -----------------------------------------------------------------------

def test_first_run_is_one_lookback_window_when_the_max_allows():
    w = sf.plan_windows(None, NOW, initial_lookback_days=90, overlap_days=5, max_days=90)
    assert len(w) == 1 and w[0].start == NOW - timedelta(days=90) and w[0].end == NOW


def test_default_max_window_splits_the_first_run():
    w = sf.plan_windows(None, NOW, initial_lookback_days=90, overlap_days=5, max_days=45)
    assert _days(w) == [45, 45] and w[0].end == w[1].start and w[-1].end == NOW


def test_old_cursor_plans_contiguous_chunks_from_cursor_minus_overlap():
    cursor = NOW - timedelta(days=200)
    w = sf.plan_windows(cursor, NOW, overlap_days=5, max_days=90)
    assert w[0].start == cursor - timedelta(days=5)
    assert _days(w) == [90, 90, 25] and all(a.end == b.start for a, b in zip(w, w[1:]))
    assert w[-1].end == NOW                                            # end exclusive == now


def test_since_backfills_and_a_current_cursor_still_reads_the_overlap():
    w = sf.plan_windows(NOW - timedelta(days=1), NOW, since=date(2026, 6, 1), max_days=90)
    assert w[0].start == datetime(2026, 6, 1, tzinfo=UTC) and _days(w) == [90, 22]
    w = sf.plan_windows(NOW, NOW, overlap_days=5, max_days=90)
    assert _days(w) == [5]                                             # overlap behind a fresh cursor
    assert sf.plan_windows(NOW + timedelta(days=1), NOW, overlap_days=0) == []


def test_naive_cursor_is_read_as_utc():
    w = sf.plan_windows(datetime(2026, 9, 1), NOW, overlap_days=0, max_days=90)
    assert w[0].start == datetime(2026, 9, 1, tzinfo=UTC)


# --- budget -------------------------------------------------------------------------------

def test_budget_allows_truncates_and_floors_at_zero():
    assert sf.budget_allows(0, 3, 20) == 3
    assert sf.budget_allows(18, 3, 20) == 2
    assert sf.budget_allows(20, 3, 20) == 0 and sf.budget_allows(25, 3, 20) == 0


def test_requests_used_today_counts_only_today_utc(store_db):
    today = datetime(NOW.year, NOW.month, NOW.day, 0, 5, tzinfo=UTC)
    sync_runs.insert_many([
        {"feed": "simplefin", "started_at": today, "requests_used": 3, "status": "ok"},
        {"feed": "simplefin", "started_at": NOW, "requests_used": 4, "status": "partial"},
        {"feed": "simplefin", "started_at": today - timedelta(minutes=10), "requests_used": 9, "status": "ok"},
        {"feed": "sheets", "started_at": NOW, "requests_used": 9, "status": "ok"},
    ])
    assert sf.requests_used_today(NOW) == 7


# --- the run: chunks, budget, cursor --------------------------------------------------------

def chunked_client(responses):
    """A client whose n-th call gets responses[n]: a dict body, or an int status."""
    calls = []
    def handler(r: httpx.Request):
        i = len(calls)
        calls.append((r.url.params.get("start-date"), r.url.params.get("end-date")))
        resp = responses[min(i, len(responses) - 1)]
        return httpx.Response(resp, json={}) if isinstance(resp, int) else httpx.Response(200, json=resp)
    c = SimpleFinClient(ACCESS, transport=httpx.MockTransport(handler))
    c.calls = calls
    return c


def test_run_fetches_each_chunk_and_advances_the_cursor_per_chunk(store_db, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 45)
    c = chunked_client([payload()])
    s = sf.run_sync(client=c, now=NOW)
    assert s.status == "ok" and (s.chunks, s.chunks_done, s.requests_used) == (2, 2, 2)
    assert len(c.calls) == 2 and c.calls[0][1] == c.calls[1][0]         # contiguous
    cur = sync_cursors.get("simplefin")
    assert cur["window_end"].replace(tzinfo=UTC) == NOW
    run = sync_runs.get(s.run_id)
    assert run["chunks"] == 2 and run["requests_used"] == 2 and run["status"] == "ok"
    # next run starts overlap_days behind the cursor: one short chunk
    c2 = chunked_client([payload()])
    s2 = sf.run_sync(client=c2, now=NOW + timedelta(hours=6))
    assert s2.chunks == 1 and int(c2.calls[0][0]) == int((NOW - timedelta(days=5)).timestamp())


def test_budget_truncates_and_skips(store_db, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 30)      # 90-day first run → 3 chunks
    sync_runs.insert({"feed": "simplefin", "started_at": NOW, "requests_used": 18, "status": "ok"})
    c = chunked_client([payload()])
    s = sf.run_sync(client=c, now=NOW, budget=20)
    assert s.status == "ok" and (s.chunks, s.chunks_done, s.requests_used_today) == (3, 2, 18)
    assert len(c.calls) == 2
    cur = sync_cursors.get("simplefin")
    assert cur["window_end"].replace(tzinfo=UTC) == NOW - timedelta(days=30)   # third chunk waits

    c3 = chunked_client([payload()])
    s3 = sf.run_sync(client=c3, now=NOW + timedelta(minutes=1), budget=20)
    assert s3.status == "skipped_budget" and len(c3.calls) == 0
    run = sync_runs.get(s3.run_id)
    assert run["status"] == "skipped_budget" and "budget spent" in run["error"]
    assert (sync_cursors.get("simplefin"))["window_end"] == cur["window_end"]


def test_failure_in_chunk_two_keeps_chunk_one_and_marks_partial(store_db, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 45)
    c = chunked_client([payload(), 500])
    s = sf.run_sync(client=c, now=NOW)
    assert s.status == "partial" and (s.chunks, s.chunks_done, s.requests_used) == (2, 1, 2)
    assert "500" in s.error
    assert transactions.count() == 2                             # chunk one committed
    cur = sync_cursors.get("simplefin")
    assert cur["window_end"].replace(tzinfo=UTC) == NOW - timedelta(days=45)   # advanced to chunk one's end only
    assert (sync_runs.get(s.run_id))["status"] == "partial"


@pytest.mark.parametrize("status", [403, 402])
def test_auth_failure_aborts_without_touching_the_cursor(store_db, monkeypatch, status):
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 45)
    c = chunked_client([status])
    s = sf.run_sync(client=c, now=NOW)
    assert s.status == "failed" and len(c.calls) == 1                  # no second chunk attempted
    assert sync_cursors.get("simplefin") is None and transactions.count() == 0
    run = sync_runs.get(s.run_id)
    assert run["status"] == "failed" and str(status) in run["error"] and run["requests_used"] == 1


def test_auth_failure_after_a_good_chunk_keeps_that_chunk(store_db, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 45)
    s = sf.run_sync(client=chunked_client([payload(), 403]), now=NOW)
    assert s.status == "failed" and s.chunks_done == 1 and transactions.count() == 2
    assert (sync_cursors.get("simplefin"))["window_end"].replace(tzinfo=UTC) == NOW - timedelta(days=45)


def test_dry_run_plans_but_writes_nothing(store_db, monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 45)
    c = chunked_client([payload()])
    s = sf.run_sync(client=c, now=NOW, dry_run=True)
    assert s.status == "ok" and s.chunks == 2 and s.chunks_done == 2 and s.txns_new == 4
    assert sync_runs.count() == 1 and sync_cursors.get("simplefin") is None   # the run row only
    assert "2/2 chunks" in sf.format_summary(s)


def test_config_documented():
    from pathlib import Path
    env = Path(".env.example").read_text()
    for k in ("SIMPLEFIN_DAILY_BUDGET", "SIMPLEFIN_INITIAL_LOOKBACK_DAYS", "SIMPLEFIN_OVERLAP_DAYS",
              "SIMPLEFIN_MAX_WINDOW_DAYS"):
        assert k in env and hasattr(config, k)
