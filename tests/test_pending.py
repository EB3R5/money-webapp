"""Pending reconciliation (app/simplefin/pending.py) through whole Sync runs against a
mocked Bridge: a posted twin replaces its pending row with the app fields carried and an
audit row written; a same-id flip updates in place; two candidates are left alone;
vanished pendings are dropped after 7 days."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import config
from app.simplefin import pending, sync as sf
from app.simplefin.client import SimpleFinClient
from app.store.deletions import deletions
from app.store.transactions import transactions
from tests import dbhelper

ACCESS = "https://u:p@bridge.test/simplefin"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
DAY = int(datetime(2026, 9, 18, tzinfo=UTC).timestamp())


@pytest.fixture(autouse=True)
def _one_chunk(monkeypatch):
    monkeypatch.setattr(config, "SIMPLEFIN_MAX_WINDOW_DAYS", 90)


def body(txns):
    return {"connections": [{"conn_id": "c1", "name": "Bank"}],
            "accounts": [{"id": "acc-1", "name": "Checking", "conn_id": "c1", "balance": "1",
                          "transactions": txns}]}


def client(txns):
    return SimpleFinClient(ACCESS, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body(txns))))


def txn(id_, amount="-4.50", desc="COFFEE HUT", posted=DAY, pending_=False):
    return {"id": id_, "posted": posted, "amount": amount, "description": desc, "pending": pending_}


def _run(txns, now=NOW):
    return sf.run_sync(client=client(txns), now=now)


def test_posted_twin_replaces_pending_with_fields_carried_and_audit(store_db):
    _run([txn("p1", pending_=True)])
    pid = sf.txn_row_id("acc-1", "p1")
    transactions.update(pid, {"Category": "Food", "Group": "Variable", "Pred:Category": "Food", "Pred:Conf": 0.9})

    s = _run([txn("q1", desc="COFFEE HUT #123 POS", posted=DAY + 2 * 86400)])   # twin: new id, +2 days
    assert s.txns_pending_replaced == 1 and s.txns_new == 1
    assert transactions.get(pid) is None
    posted = transactions.get(sf.txn_row_id("acc-1", "q1"))
    assert posted["Category"] == "Food" and posted["Group"] == "Variable" and posted["Pred:Conf"] == 0.9
    assert posted["pending"] is False
    audit = dbhelper.one(deletions, reason="pending_replaced")
    assert audit["collection"] == "transactions" and audit["doc"]["_id"] == pid and audit["doc"]["Category"] == "Food"
    run = sf.sync_runs.get(s.run_id)
    assert run["txns_pending_replaced"] == 1 and run["txns_pending_dropped"] == 0


def test_same_id_flip_updates_in_place_without_deletion(store_db):
    _run([txn("p1", pending_=True)])
    pid = sf.txn_row_id("acc-1", "p1")
    transactions.update(pid, {"Category": "Food"})
    s = _run([txn("p1")])
    assert (s.txns_new, s.txns_updated, s.txns_pending_replaced) == (0, 1, 0)
    row = transactions.get(pid)
    assert row["pending"] is False and row["Category"] == "Food"
    assert deletions.count() == 0 and transactions.count() == 1


def test_two_candidates_are_left_alone(store_db):
    _run([txn("p1", pending_=True), txn("p2", pending_=True, posted=DAY + 86400)])
    s = _run([txn("q1", posted=DAY + 86400)])
    assert s.txns_pending_replaced == 0
    assert transactions.count() == 3 and deletions.count() == 0


def test_no_match_on_amount_date_or_description(store_db):
    _run([txn("p1", pending_=True), txn("p2", pending_=True, amount="-9.00", desc="SHELL")])
    s = _run([txn("q1", amount="-4.51"),                               # amount differs
                    txn("q2", amount="-4.50", posted=DAY + 5 * 86400),        # > 3 days
                    txn("q3", amount="-9.00", desc="CHEVRON")])               # description differs
    assert s.txns_pending_replaced == 0 and transactions.count() == 5


def test_vanished_pending_is_dropped_after_seven_days_and_recent_one_stays(store_db):
    _run([txn("old", pending_=True), txn("fresh", pending_=True, posted=DAY + 86400)])
    old_id, fresh_id = sf.txn_row_id("acc-1", "old"), sf.txn_row_id("acc-1", "fresh")
    # a run 6 days later still sees "fresh" (re-sent by the provider) but not "old"
    s = _run([txn("fresh", pending_=True, posted=DAY + 86400)], now=NOW + timedelta(days=6))
    assert s.txns_pending_dropped == 0 and transactions.get(old_id) is not None
    # 8 days after the first run, "old" has been unseen for 8 days → dropped; "fresh" was seen 2 days ago → stays
    s = _run([], now=NOW + timedelta(days=8))
    assert s.txns_pending_dropped == 1
    assert transactions.get(old_id) is None and transactions.get(fresh_id) is not None
    audit = dbhelper.one(deletions, reason="pending_vanished")
    assert audit["doc"]["_id"] == old_id
    assert (sf.sync_runs.get(s.run_id))["txns_pending_dropped"] == 1


def test_vanished_only_inside_the_widened_window(store_db):
    _run([txn("old", pending_=True, posted=DAY - 200 * 86400)])   # dated long before any later window
    s = _run([], now=NOW + timedelta(days=8))
    assert s.txns_pending_dropped == 0                                    # outside the window: not judged
    assert transactions.count() == 1


def test_description_matching():
    assert pending.descriptions_match("Coffee  Hut", "coffee hut")
    assert pending.descriptions_match("COFFEE HUT #123", "coffee hut")
    assert pending.descriptions_match("coffee", "COFFEE HUT #123")
    assert not pending.descriptions_match("Coffee Hut", "Shell")
    assert pending.descriptions_match("", "") and not pending.descriptions_match("", "x")


def test_edited_pending_row_still_matches_and_carries_its_edits(store_db):
    """ADR-0019: a pending row the person edited (Amount and Description) still finds its
    posted twin on the bank's values, and the edits ride onto the posted row."""
    _run([txn("p1", pending_=True)])
    pid = sf.txn_row_id("acc-1", "p1")
    transactions.update(pid, {"Amount": -4.49, "Description": "Coffee with Sam", "Category": "Food"})
    s = _run([txn("q1", desc="COFFEE HUT #123 POS", posted=DAY + 2 * 86400)])
    assert s.txns_pending_replaced == 1 and transactions.get(pid) is None
    posted = transactions.get(sf.txn_row_id("acc-1", "q1"))
    assert posted["Description"] == "Coffee with Sam" and posted["Amount"] == -4.49 and posted["Category"] == "Food"
    assert posted["_provider"]["Amount"] == -4.5 and posted["_provider"]["Description"] == "COFFEE HUT #123 POS"
    # and the next run keeps them: they are hand edits on the posted row now
    _run([txn("q1", desc="COFFEE HUT #123 POS", posted=DAY + 2 * 86400)])
    posted = transactions.get(sf.txn_row_id("acc-1", "q1"))
    assert posted["Description"] == "Coffee with Sam" and posted["Amount"] == -4.49
    audit = dbhelper.one(deletions, reason="pending_replaced")
    assert audit["doc"]["Description"] == "Coffee with Sam"
