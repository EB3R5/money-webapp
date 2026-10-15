"""SimpleFIN sync run (app/simplefin/sync.py) against a mocked Bridge: idempotent upserts
through the stores, protected app-owned fields, one Snapshot per Account per day, Rules and
ML suggestions on the rows a run inserts, a sync_runs row per run, dry run writes nothing,
unset Access URL is a no-op."""

from datetime import UTC, datetime

import httpx
import pytest

from app import config
from app.categorization import ml_model
from app.simplefin import sync as sf
from app.store.autocat import autocat
from app.simplefin.client import SimpleFinClient
from app.store.accounts import accounts
from app.store.balance_history import balance_history
from app.store.connections import connections
from app.store.sync_cursors import sync_cursors
from app.store.sync_runs import sync_runs
from app.store.transactions import transactions

ACCESS = "https://u:p@bridge.test/simplefin"


@pytest.fixture(autouse=True)
def _one_chunk(monkeypatch):
    """This suite is about applying an account set; keep a 90-day first run to one chunk.
    Chunking, budget, and the per-chunk cursor are tests/test_sync_windows.py."""
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 90)
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
POSTED = int(datetime(2026, 9, 20, tzinfo=UTC).timestamp())      # 2026-09-20 00:00:00 UTC

def payload(desc="Coffee Hut", amount="-4.50", errlist=None, extra_txn=None):
    txns = [{"id": "t1", "posted": POSTED, "amount": amount, "description": desc, "pending": False,
             "extra": {"category": "food"}},
            {"id": "t2", "posted": POSTED + 3600, "amount": "-9.00", "description": "Shell", "pending": True}]
    if extra_txn:
        txns.append(extra_txn)
    return {
        "errlist": errlist or [],
        "connections": [{"conn_id": "c1", "name": "Demo Bank", "org_id": "demo", "sfin_url": "https://x/sfin"}],
        "accounts": [{"id": "acc-1", "name": "Checking", "conn_id": "c1", "currency": "USD",
                      "balance": "1234.56", "available-balance": "1200.00", "balance-date": POSTED,
                      "transactions": txns}],
    }


def client_for(body=None, status=200):
    calls = []
    def handler(r: httpx.Request):
        calls.append(str(r.url))
        return httpx.Response(status, json=body if body is not None else payload())
    c = SimpleFinClient(ACCESS, transport=httpx.MockTransport(handler))
    c.calls = calls
    return c


def test_pending_row_with_no_posted_epoch_is_dated_by_transacted_at(store_db):
    """SimpleFIN v2 sends `posted: 0` for a pending transaction; the row is dated by
    `transacted_at` (or the run, failing that), never 1970-01-01, and posted_at stays empty."""
    body = payload(extra_txn={"id": "t3", "posted": 0, "transacted_at": POSTED + 86400,
                              "amount": "-3.00", "description": "Pending coffee", "pending": True})
    body["accounts"][0]["transactions"].append(
        {"id": "t4", "posted": 0, "amount": "-1.00", "description": "No dates", "pending": True})
    sf.run_sync(trigger="manual", client=client_for(body), now=NOW)
    t3 = transactions.get(sf.txn_row_id("acc-1", "t3"))
    assert t3["Date"] == datetime(2026, 9, 21) and t3["Month"] == datetime(2026, 9, 1)
    assert t3["posted_at"] is None and t3["pending"] is True
    t4 = transactions.get(sf.txn_row_id("acc-1", "t4"))
    assert t4["Date"] == datetime(2026, 9, 21) and t4["posted_at"] is None
    assert transactions.count({"Date": datetime(1970, 1, 1)}) == 0


def test_first_run_writes_everything(store_db):
    s = sf.run_sync(trigger="manual", client=client_for(), now=NOW)
    assert s.status == "ok" and s.requests_used == 1
    assert (s.connections_seen, s.accounts_seen, s.txns_new, s.txns_updated, s.snapshots_added) == (1, 1, 2, 0, 1)

    c = connections.get("c1")
    assert c["name"] == "Demo Bank" and c["last_seen_at"] is not None
    a = accounts.one({"simplefin_account_id": "acc-1"})
    assert a["Account"] == "Checking" and a["Account ID"] == "acc-1" and a["Institution"] == "Demo Bank"
    assert a["Amount"] == 1234.56 and a["available"] == 1200.0
    assert a["Status"] == "Unlinked" and a["is_hidden"] is True         # a placeholder, not a card
    assert a["currency"] == "USD" and a["connection_id"] == "c1"

    t = transactions.get(sf.txn_row_id("acc-1", "t1"))
    assert t["source"] == "simplefin" and t["provider_account_id"] == "acc-1" and t["provider_txn_id"] == "t1"
    assert t["Date"] == datetime(2026, 9, 20) and t["Month"] == datetime(2026, 9, 1)
    assert t["Amount"] == -4.5 and t["Description"] == "Coffee Hut" and t["Account"] == "Checking"
    assert t["pending"] is False and t["Metadata"] == '{"category": "food"}' and t["Category"] is None
    assert (transactions.get(sf.txn_row_id("acc-1", "t2")))["pending"] is True

    snap = balance_history.one({"Account ID": "acc-1"})
    assert snap["Balance"] == 1234.56 and snap["available"] == 1200.0 and snap["_src"] == "simplefin"
    assert snap["sync_run_id"] == s.run_id and snap["Month"] == "2026-09"

    run = sync_runs.get(s.run_id)
    assert run["status"] == "ok" and run["trigger"] == "manual" and run["txns_new"] == 2
    assert run["snapshots_added"] == 1 and run["finished_at"] is not None and run["errlist"] == []
    cur = sync_cursors.get("simplefin")
    assert cur["window_end"].replace(tzinfo=None) == NOW.replace(tzinfo=None)


def test_second_run_same_day_refreshes_the_days_snapshot(store_db):
    first = sf.run_sync(client=client_for(), now=NOW)
    body = payload()
    body["accounts"][0]["balance"] = "1300.00"
    s = sf.run_sync(client=client_for(body), now=NOW)
    assert (s.txns_new, s.txns_updated, s.snapshots_added, s.snapshots_replaced) == (0, 0, 0, 1)
    assert transactions.count() == 2 and accounts.count() == 1 and connections.count() == 1
    assert balance_history.count() == 1                       # one Snapshot per Account per day
    snap = balance_history.one({"Account ID": "acc-1"})
    assert snap["Balance"] == 1300.0 and snap["sync_run_id"] == s.run_id != first.run_id
    assert snap["Date"] == datetime(2026, 9, 20)                     # the balance date's day
    assert sync_runs.count() == 2


def test_a_new_balance_day_adds_a_second_snapshot(store_db):
    sf.run_sync(client=client_for(), now=NOW)
    body = payload()
    body["accounts"][0]["balance-date"] = POSTED + 86400            # the next day
    s = sf.run_sync(client=client_for(body), now=NOW)
    assert (s.snapshots_added, s.snapshots_replaced) == (1, 0)
    days = sorted(r["Date"] for r in balance_history.list())
    assert days == [datetime(2026, 9, 20), datetime(2026, 9, 21)]


def test_sync_categorizes_what_it_inserts(store_db, monkeypatch):
    from tests import dbhelper
    dbhelper.seed_ledger()                                     # Food's derived fields
    autocat.insert({"_id": "r1", "Category": "Food", "Description Contains": "coffee",
                          "order": 1, "enabled": True})
    calls = []

    def fake_predict(description, amount=0.0):
        calls.append(description)
        return [{"category": "Fuel", "confidence": 0.8}] if "shell" in (description or "").lower() else []
    monkeypatch.setattr(ml_model, "predict", fake_predict)

    s = sf.run_sync(client=client_for(), now=NOW)
    assert (s.txns_new, s.rules_applied, s.ml_suggested) == (2, 1, 1)
    coffee = transactions.get(sf.txn_row_id("acc-1", "t1"))
    assert coffee["Category"] == "Food" and coffee["Group"] == "Variable"   # the Rule and its cascade
    assert coffee["Pred:Category"] is None                                   # no suggestion once categorized
    shell = transactions.get(sf.txn_row_id("acc-1", "t2"))
    assert shell["Category"] is None and shell["Pred:Category"] == "Fuel" and shell["Pred:Conf"] == 0.8
    assert calls == ["Shell"]                                                # ML only saw the still-blank row
    run = sync_runs.get(s.run_id)
    assert run["rules_applied"] == 1 and run["ml_suggested"] == 1
    # a second run inserts nothing, so it categorizes nothing and touches no existing row
    s2 = sf.run_sync(client=client_for(), now=NOW)
    assert (s2.rules_applied, s2.ml_suggested) == (0, 0) and calls == ["Shell"]
    assert "categorized by rules 1  ML suggestions 1" in sf.format_summary(s)


def test_provider_change_counts_and_app_fields_survive(store_db):
    sf.run_sync(client=client_for(), now=NOW)
    tid = sf.txn_row_id("acc-1", "t1")
    transactions.update(tid, {"Category": "Food", "Group": "Variable", "Pred:Category": "X"})
    aid = (accounts.one({"simplefin_account_id": "acc-1"}))["_id"]
    accounts.update(aid, {"Account": "My Checking", "Type": "Assets", "Group": "Cash", "Status": "Closed"})

    s = sf.run_sync(client=client_for(payload(desc="Coffee Hut #2", amount="-4.50")), now=NOW)
    # t1's description changed; both rows pick up the renamed Account text (provider-stamped).
    assert (s.txns_new, s.txns_updated) == (0, 2)
    t = transactions.get(tid)
    assert t["Description"] == "Coffee Hut #2" and t["Account"] == "My Checking"
    assert (transactions.get(sf.txn_row_id("acc-1", "t2")))["Account"] == "My Checking"
    # an unchanged third run counts nothing as updated
    s = sf.run_sync(client=client_for(payload(desc="Coffee Hut #2", amount="-4.50")), now=NOW)
    assert (s.txns_new, s.txns_updated) == (0, 0)
    assert t["Category"] == "Food" and t["Group"] == "Variable" and t["Pred:Category"] == "X"   # protected
    a = accounts.get(aid)
    assert a["Account"] == "My Checking" and a["Type"] == "Assets" and a["Status"] == "Closed"   # protected
    assert a["Amount"] == 1234.56                                     # provider fact refreshed
    # snapshots and transactions written after a rename carry the app's name
    assert (balance_history.list(order=[("_created_at", "desc")]))[0]["Account"] == "My Checking"


def test_new_transaction_in_a_later_run(store_db):
    sf.run_sync(client=client_for(), now=NOW)
    body = payload(extra_txn={"id": "t3", "posted": POSTED + 7200, "amount": "12.00", "description": "Refund"})
    s = sf.run_sync(client=client_for(body), now=NOW)
    assert (s.txns_new, s.txns_updated) == (1, 0) and transactions.count() == 3


def test_dry_run_writes_only_its_run_row_and_spends_the_budget(store_db):
    """A dry run calls the Bridge for real, so it is recorded (status dry_run) and counts
    toward the day's budget; the ledger, the accounts and the cursor are untouched."""
    s = sf.run_sync(dry_run=True, client=client_for(), now=NOW)
    assert s.status == "ok" and s.dry_run and s.run_id
    assert s.accounts_seen == 1 and s.txns_new == 2
    for st in (transactions, accounts, connections, balance_history, sync_cursors):
        assert st.count() == 0
    row = sync_runs.get(s.run_id)
    assert row["status"] == "dry_run" and row["trigger"] == "cli" and row["requests_used"] >= 1
    assert sf.requests_used_today(NOW) == row["requests_used"]
    # repeated dry runs cannot exhaust the budget unrecorded
    assert sf.run_sync(dry_run=True, client=client_for(), now=NOW, budget=1).status == "skipped_budget"


def test_the_lock_is_taken_before_the_busy_check(store_db):
    """Two callers in the same instant: the second gets SyncBusy, never a second run."""
    import threading
    started, release = threading.Event(), threading.Event()

    class SlowClient:
        requests_made = 0

        def fetch_accounts(self, *a, **k):
            started.set(); release.wait(5)
            return client_for().fetch_accounts(*a, **k)
    results = {}

    def first():
        results["first"] = sf.run_sync(client=SlowClient(), now=NOW)
    t = threading.Thread(target=first); t.start()
    assert started.wait(5)
    with pytest.raises(sf.SyncBusy):
        sf.run_sync(client=client_for(), now=NOW)
    release.set(); t.join(5)
    assert results["first"].status == "ok" and sync_runs.count() == 1


def test_unset_access_url_is_a_noop_with_a_warning(store_db, monkeypatch, caplog):
    monkeypatch.setattr(config, "SIMPLEFIN_ACCESS_URL", "")
    import logging
    with caplog.at_level(logging.WARNING, logger="money.simplefin"):
        s = sf.run_sync(now=NOW)
    assert s.status == "skipped_unconfigured" and sync_runs.count() == 0
    assert any("SIMPLEFIN_ACCESS_URL" in r.getMessage() for r in caplog.records)


def test_errlist_is_sanitized_and_connection_codes_mark_partial(store_db):
    body = payload(errlist=[{"code": "con.refresh", "msg": "Bank\x00 is\n refreshing https://u:p@bridge.test/x " + "x" * 400,
                             "conn_id": "c1"}])
    s = sf.run_sync(client=client_for(body), now=NOW)
    assert s.status == "partial"
    msg = s.errlist[0]["msg"]
    assert "\x00" not in msg and "\n" not in msg and "u:p@" not in msg and len(msg) <= 300
    run = sync_runs.get(s.run_id)
    assert run["status"] == "partial" and run["errlist"][0]["code"] == "con.refresh"
    # the chunk itself applied, so the cursor advances; only a failed chunk leaves it alone
    assert (sync_cursors.get("simplefin"))["window_end"].replace(tzinfo=UTC) == NOW


@pytest.mark.parametrize("status", [403, 402])
def test_auth_and_payment_failures_are_recorded(store_db, status):
    s = sf.run_sync(client=client_for({}, status=status), now=NOW)
    assert s.status == "failed" and str(status) in s.error and s.requests_used == 1
    run = sync_runs.get(s.run_id)
    assert run["status"] == "failed" and run["error"] == s.error and run["finished_at"] is not None
    assert sync_cursors.get("simplefin") is None


def test_since_sets_the_window(store_db):
    from datetime import date
    c = client_for()
    s = sf.run_sync(client=c, now=NOW, since=date(2026, 6, 1))
    assert s.window_start.startswith("2026-06-01") and s.window_end.startswith("2026-09-21")
    start = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
    assert f"start-date={start}" in c.calls[0] and "pending=1" in c.calls[0] and "version=2" in c.calls[0]


def test_helpers():
    assert sf.txn_row_id("a", "t") == sf.txn_row_id("a", "t") and sf.txn_row_id("a", "t") != sf.txn_row_id("a", "u")
    assert sf.epoch_to_day(POSTED + 86399) == datetime(2026, 9, 20)
    assert sf.sanitize_msg("  a \t b\x07c  ") == "a bc"                # control char dropped, whitespace collapsed
    assert sf.sanitize_msg("x" * 500) == "x" * 300
    assert "simplefin sync: ok" in sf.format_summary(sf.SyncSummary())


# --- hand edits survive a run (ADR-0019) -------------------------------------------------------

from app.store.transactions import hand_edits, provider_norm, provider_same  # noqa: E402

TID = sf.txn_row_id("acc-1", "t1")


def test_provider_norm_and_same_rules():
    aware = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
    assert provider_norm("posted_at", aware) == "2026-09-20T00:00:00"
    assert provider_norm("Date", datetime(2026, 9, 20)) == provider_norm("Date", aware)
    assert provider_norm("Date", "2026-09-20T00:00:00+00:00") == "2026-09-20T00:00:00"
    assert provider_norm("Date", datetime(2026, 9, 20).date()) == "2026-09-20T00:00:00"
    assert provider_norm("pending", 1) is True and provider_norm("pending", 0) is False
    assert provider_norm("Description", "") is None and provider_norm("Description", None) is None
    assert provider_norm("Amount", "-4.50") == -4.5
    assert provider_same("Amount", -4.5, -4.5000000001) and not provider_same("Amount", -4.5, -4.49)
    assert provider_same("Description", None, None) and not provider_same("Description", "a", None)


def test_hand_edits_on_every_editable_field_survive_a_later_run(store_db):
    sf.run_sync(client=client_for(), now=NOW)
    mine = {"Date": datetime(2026, 9, 1), "Description": "Coffee with Sam", "Amount": -4.0,
            "Account": "Joint", "Institution": "Credit Union"}
    transactions.update(TID, mine)
    s = sf.run_sync(client=client_for(), now=NOW)
    t = transactions.get(TID)
    for k, v in mine.items():
        assert t[k] == v, k
    assert t["Month"] == datetime(2026, 9, 1)                 # follows the edited Date
    assert (s.txns_updated, s.txns_hand_kept) == (0, 0)       # nothing changed, nothing to keep
    assert t["_provider"]["Amount"] == -4.5 and t["_provider"]["Description"] == "Coffee Hut"
    assert set(hand_edits(t)) == set(mine)


def test_bank_change_arrives_on_unedited_fields_and_a_conflict_keeps_the_edit(store_db):
    sf.run_sync(client=client_for(), now=NOW)
    transactions.update(TID, {"Description": "Mine"})
    # the bank changes the amount (unedited → arrives) and the description (edited → kept)
    s = sf.run_sync(client=client_for(payload(desc="Coffee Hut #2", amount="-5.00")), now=NOW)
    t = transactions.get(TID)
    assert t["Amount"] == -5.0 and t["Description"] == "Mine"
    assert (s.txns_updated, s.txns_hand_kept) == (1, 1)
    assert t["_provider"]["Description"] == "Coffee Hut #2" and t["_provider"]["Amount"] == -5.0
    # a third identical run: nothing to update, the edit still stands
    s = sf.run_sync(client=client_for(payload(desc="Coffee Hut #2", amount="-5.00")), now=NOW)
    assert (s.txns_updated, s.txns_hand_kept) == (0, 0)
    assert (transactions.get(TID))["Description"] == "Mine"


def test_legacy_row_without_snapshot_keeps_its_values_then_follows_the_bank(store_db):
    sf.run_sync(client=client_for(), now=NOW)
    transactions.update(TID, {"_provider": None, "Description": "Edited before 0013"})
    s = sf.run_sync(client=client_for(payload(desc="Coffee Hut #2")), now=NOW)
    t = transactions.get(TID)
    assert t["Description"] == "Edited before 0013" and t["_provider"]["Description"] == "Coffee Hut #2"
    assert (s.txns_updated, s.txns_hand_kept) == (0, 0)       # first run only starts the snapshot
    # the person's text differs from the new snapshot → it is a hand edit from now on
    s = sf.run_sync(client=client_for(payload(desc="Coffee Hut #3")), now=NOW)
    assert (transactions.get(TID))["Description"] == "Edited before 0013"
    assert s.txns_hand_kept == 1
    # an unedited field still follows the bank
    s = sf.run_sync(client=client_for(payload(desc="Coffee Hut #3", amount="-6.00")), now=NOW)
    assert (transactions.get(TID))["Amount"] == -6.0 and s.txns_updated == 1


def test_same_id_pending_to_posted_flip_still_updates_the_feed_fields(store_db):
    body = payload(extra_txn={"id": "t3", "posted": 0, "transacted_at": POSTED + 86400,
                              "amount": "-3.00", "description": "PENDING COFFEE", "pending": True})
    sf.run_sync(client=client_for(body), now=NOW)
    t3 = sf.txn_row_id("acc-1", "t3")
    transactions.update(t3, {"Description": "Coffee, pending"})
    body = payload(extra_txn={"id": "t3", "posted": POSTED + 2 * 86400, "amount": "-3.00",
                              "description": "COFFEE HUT #123", "pending": False})
    s = sf.run_sync(client=client_for(body), now=NOW)
    t = transactions.get(t3)
    assert t["pending"] is False and t["posted_at"] == datetime(2026, 9, 22, tzinfo=UTC)
    assert t["Date"] == datetime(2026, 9, 22)                 # Date was not edited → follows the bank
    assert t["Description"] == "Coffee, pending"              # edited → kept
    assert s.txns_updated == 1 and s.txns_hand_kept == 1


def test_linked_institution_survives_the_next_run(store_db):
    sf.run_sync(client=client_for(), now=NOW)
    # what link._rekey_rows does: the card's Institution onto every feed row of the account
    transactions.update_where({"provider_account_id": "acc-1"}, {"Institution": "My Bank"})
    s = sf.run_sync(client=client_for(), now=NOW)
    assert (transactions.get(TID))["Institution"] == "My Bank"
    assert s.txns_updated == 0
