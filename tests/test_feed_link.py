"""Feed accounts arrive unlinked (app/simplefin/link.py): a hidden placeholder that still
collects rows; Link moves everything under an existing card, Promote makes it a card,
Ignore removes its rows and has the sync skip it; every operation is audited."""

import pytest

from app.simplefin import link, sync as sf
from app.store.accounts import accounts
from app.store.balance_history import balance_history
from app.store.deletions import deletions
from app.store.transactions import transactions
from app.web import DomainError
from tests import dbhelper
from tests.test_simplefin_sync import NOW, POSTED, client_for, payload

PRESET = {"Type": "Assets", "Group": "Current Assets", "Category": "Checking Account",
          "Account Type": "Checking Account"}


def _first_run():
    sf.run_sync(client=client_for(), now=NOW)
    return accounts.one({"simplefin_account_id": "acc-1"})


def test_placeholder_is_hidden_and_still_collects_rows(store_client):
    ph = _first_run()
    assert link.is_placeholder(ph) and ph["Status"] == "Unlinked" and ph["is_hidden"] is True
    assert [p["_id"] for p in link.unlinked()] == [ph["_id"]]
    assert transactions.count({"provider_account_id": "acc-1"}) == 2        # D9: collected
    assert (balance_history.one({"_src": "simplefin"}))["Account"] == "Checking"
    assert f'data-id="{ph["_id"]}"' not in (store_client.get("/accounts?status=all")).text  # no card


def test_link_moves_rows_under_the_card_and_later_runs_write_there(store_client):
    dbhelper.seed_accounts()                     # acc1 = "Checking" card, Account ID A1, Assets
    ph = _first_run()
    res = link.link(ph["_id"], "acc1")
    assert res == {"ok": True, "card": "acc1", "transactions": 2, "snapshots": 1}

    card = accounts.get("acc1")
    assert card["simplefin_account_id"] == "acc-1" and card["connection_id"] == "c1"
    assert card["available"] == 1200.0 and card["currency"] == "USD"
    assert card["Amount"] == 1000.0                    # the card's own facts until the next run
    for t in transactions.list({"provider_account_id": "acc-1"}):
        assert t["Account"] == "Checking" and t["Institution"] == "Demo Bank"   # card has none → the bank's
    snap = balance_history.one({"_src": "simplefin"})
    assert snap["Account ID"] == "A1" and snap["Class"] == "Assets" and snap["Institution"] == "Demo Bank"
    assert accounts.get(ph["_id"]) is None
    logged = deletions.one({"collection": "accounts", "reason": "feed_linked"})
    assert logged["doc"]["_id"] == ph["_id"]
    assert link.unlinked() == []

    # the next run finds the card by feed id: refreshes its facts, creates no placeholder
    body = payload(extra_txn={"id": "t3", "posted": POSTED + 7200, "amount": "12.00", "description": "Refund"})
    body["accounts"][0]["balance"] = "1300.00"
    s = sf.run_sync(client=client_for(body), now=NOW)
    assert s.txns_new == 1 and accounts.count() == 4          # the four seeded cards, no fifth row
    card = accounts.get("acc1")
    assert card["Amount"] == 1300.0 and card["Status"] == "Open" and not card["is_hidden"]
    assert (transactions.get(sf.txn_row_id("acc-1", "t3")))["Account"] == "Checking"
    assert (balance_history.one({"_src": "simplefin"}))["Balance"] == 1300.0   # same day, refreshed
    assert 'data-id="acc1"' in (store_client.get("/accounts")).text


def test_link_guards(store_client):
    dbhelper.seed_accounts()
    ph = _first_run()
    with pytest.raises(DomainError):
        link.link("nope", "acc1")
    with pytest.raises(DomainError):
        link.link(ph["_id"], "nope")
    with pytest.raises(DomainError):
        link.link("acc1", "acc2")                # a card is not a placeholder
    link.link(ph["_id"], "acc1")
    ph2 = accounts.insert({"_id": "sfa_two", "simplefin_account_id": "acc-2", "Account ID": "acc-2",
                                 "Account": "Other", "Status": "Unlinked", "is_hidden": True})
    with pytest.raises(DomainError):                   # a card links to one feed account only
        link.link(ph2, "acc1")


def test_promote_makes_a_classified_card(store_client):
    ph = _first_run()
    res = link.promote(ph["_id"], "Bank/cash", PRESET)
    assert res["ok"] and res["card"] == ph["_id"] and res["snapshots"] == 1
    card = accounts.get(ph["_id"])
    assert card["Account ID"].startswith("MAN-") and card["Status"] == "Active" and card["is_hidden"] is False
    assert card["Type"] == "Assets" and card["Account Type"] == "Checking Account"
    assert card["Account Kind"] == "Bank/cash" and card["simplefin_account_id"] == "acc-1"
    snap = balance_history.one({"_src": "simplefin"})
    assert snap["Account ID"] == card["Account ID"] and snap["Class"] == "Assets"
    assert card.get("Account #") is None                            # D10
    page = (store_client.get("/accounts")).text
    assert "Checking" in page and "Assets" in page
    with pytest.raises(DomainError):
        link.promote(ph["_id"], "Bank/cash", PRESET)          # no longer a placeholder


def test_ignore_removes_rows_and_the_sync_skips_it(store_client):
    ph = _first_run()
    res = link.ignore(ph["_id"])
    assert res == {"ok": True, "transactions": 2, "snapshots": 1}
    assert transactions.count({"provider_account_id": "acc-1"}) == 0 and balance_history.count() == 0
    assert deletions.count({"reason": "feed_ignored"}) == 3
    row = accounts.get(ph["_id"])
    assert row["Status"] == "Ignored" and row["is_hidden"] is True
    assert link.unlinked() == [] and [r["_id"] for r in link.ignored()] == [ph["_id"]]

    s = sf.run_sync(client=client_for(), now=NOW)
    assert s.accounts_seen == 1 and s.accounts_ignored == 1 and s.txns_new == 0
    assert transactions.count({"provider_account_id": "acc-1"}) == 0 and balance_history.count() == 0
    assert (accounts.get(ph["_id"]))["Amount"] == 1234.56        # provider facts still refresh
    assert "ignored 1" in sf.format_summary(s)

    link.unignore(ph["_id"])
    assert (accounts.get(ph["_id"]))["Status"] == "Unlinked"
    s = sf.run_sync(client=client_for(), now=NOW)
    assert s.txns_new == 2 and balance_history.count() == 1       # collecting again
    with pytest.raises(DomainError):
        link.unignore(ph["_id"])
