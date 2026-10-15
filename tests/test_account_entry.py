"""Dynamic account entry — the type-aware Add-account fan-out (app/views/accounts.py).

One POST to /api/accounts/row produces the account card + linked detail record
(portfolio holding / credit registry entry) + first classified balance snapshot,
written detail-first so a failed save never leaves an orphan card. Covers the plan's
AE1-AE6 (docs/plans/2026-07-15-001-feat-dynamic-account-entry-plan.md)."""

import pytest

from app import investments
from app.store.accounts import accounts
from app.store.balance_history import balance_history
from app.store.credit_accounts import credit_accounts
from app.store.deletions import deletions
from app.store.portfolio import portfolio
from tests import dbhelper

PORTFOLIO = portfolio.table




@pytest.fixture(autouse=True)
def _cards(store_client):
    """The four seeded account cards, on the store (Checking / Visa / Old Card / nameless)."""
    dbhelper.seed_accounts()


def _create(store_client, payload):
    r = store_client.post("/api/accounts/row", json=payload)
    return r, r.json()


def stock_payload(ticker="AAPL", shares="10", price="1,500", brokerage="Fidelity"):
    return {"Account Kind": "Common stock", "Ticker": ticker, "Shares": shares,
            "Purchase Price": price, "Brokerage": brokerage}


def credit_payload(name="Amex Blue", limit="5,000", apr="24.9", opening=None):
    p = {"Account Kind": "Credit card", "Account": name, "Institution": "Amex",
         "Credit Limit": limit, "APR %": apr, "Min Payment": "35"}
    if opening is not None:
        p["Opening Balance"] = opening
    return p


# --- stock ---------------------------------------------------------------------

def test_stock_create_fans_out_holding_and_snapshot(store_client):
    r, body = _create(store_client, stock_payload())
    assert body["ok"]
    card = accounts.get(body["id"])
    assert card["Account"] == "AAPL" and card["Account Kind"] == "Common stock"
    assert card["Type"] == "Equity" and card["Account Type"] == "Common Stock"
    # transient form fields never persist on the card
    for f in ("Ticker", "Shares", "Purchase Price", "Brokerage"):
        assert f not in card

    holding = portfolio.one({"Asset": "AAPL"})
    assert holding["account_id"] == card["Account ID"]
    assert holding["Shares"] == 10.0 and holding["Type"] == "Individual Stock"
    # refresh-eligible: resolvable ticker + nonzero shares
    assert investments.normalize_ticker(holding["Asset"]) == "AAPL"

    snap = balance_history.one({"_src": "account_create", "Account": "AAPL"})
    assert snap["Balance"] == 1500.0 and snap["Class"] == "Equity"
    assert snap["Institution"] == "Fidelity" and snap["Account ID"] == card["Account ID"]
    assert snap["Account Type"] == "Common Stock" and snap.get("Account #") is None


def test_stock_ticker_normalized_and_validated(store_client):
    r, body = _create(store_client, stock_payload(ticker="  brk.b "))
    assert body["ok"]
    assert portfolio.one({"Asset": "BRK.B"})

    r, body = _create(store_client, {"Account Kind": "Common stock", "Ticker": "Cash Sweep",
                                     "Shares": "5", "Purchase Price": "100"})
    assert r.status_code == 400          # cash-like assets are not resolvable tickers

    r, body = _create(store_client, stock_payload(ticker="MSFT", shares="0"))
    assert r.status_code == 400 and "Shares" in body["error"]


# --- credit --------------------------------------------------------------------

def test_credit_create_fans_out_registry_entry(store_client):
    r, body = _create(store_client, credit_payload())
    assert body["ok"]
    card = accounts.get(body["id"])
    assert card["Type"] == "Liabilities" and card["Credit Limit"] == 5000.0

    entry = credit_accounts.one({"name": "Amex Blue"})
    assert entry["credit_limit"] == 5000.0
    assert entry["apr"] == 0.249                     # percent → fraction
    assert entry["balance_account"] == "Amex Blue"   # name-keyed Credit-page join
    assert entry["account_id"] == card["Account ID"]
    assert entry["status"] == "Active"

    snap = balance_history.one({"_src": "account_create", "Account": "Amex Blue"})
    assert snap["Balance"] == 0.0                    # no opening balance → 0
    assert snap["Class"] == "Liabilities"


def test_credit_opening_balance_matches_migrated_sign(store_client):
    # A2: migrated liability rows store positive magnitudes — new ones match
    r, body = _create(store_client, credit_payload(name="Visa X", opening="750"))
    assert body["ok"]
    snap = balance_history.one({"_src": "account_create", "Account": "Visa X"})
    assert snap["Balance"] == 750.0
    card = accounts.one({"Account": "Visa X"})
    assert card["Amount"] == 750.0


# --- bank / loan -----------------------------------------------------------------

def test_bank_create_snapshot_is_fully_classified(store_client):
    r, body = _create(store_client, {"Account Kind": "Bank/cash", "Account": "Ally Savings",
                                     "Institution": "Ally", "Amount": "12,000"})
    assert body["ok"]
    snap = balance_history.one({"Account": "Ally Savings"})
    assert snap["Balance"] == 12000.0
    assert snap["Class"] == "Assets" and snap["Group"] == "Current Assets"
    assert snap["Institution"] == "Ally" and snap["Account Type"] == "Checking Account"
    assert snap["Account ID"]
    # AE3 (the balance sheet showing it) is test_ae3_bank_account_on_balance_sheet_without_stamp


def test_loan_balance_owed_matches_migrated_sign(store_client):
    r, body = _create(store_client, {"Account Kind": "Loan", "Account": "Car Loan",
                                     "Institution": "Chase", "Balance Owed": "8,200",
                                     "APR %": "6.5"})
    assert body["ok"]
    card = accounts.one({"Account": "Car Loan"})
    assert card["Amount"] == 8200.0                  # sign-consistent with the snapshot
    snap = balance_history.one({"Account": "Car Loan"})
    assert snap["Balance"] == 8200.0 and snap["Class"] == "Liabilities"
    assert portfolio.one({"Asset": "Car Loan"}) is None
    assert credit_accounts.one({"name": "Car Loan"}) is None


# --- duplicate guard + stray recovery (AE6) ----------------------------------------

def test_duplicate_active_name_rejected_archived_allowed(store_client):
    r, _ = _create(store_client, credit_payload(name="Visa Dup"))
    assert r.status_code == 200

    r, body = _create(store_client, credit_payload(name="visa dup"))
    assert r.status_code == 400 and "already exists" in body["error"]

    # archive both sides, then re-creating the same name succeeds (AE6)
    accounts.update((accounts.one({"Account": "Visa Dup"}))["_id"], {"Status": "Closed"})
    dup = credit_accounts.one({"name": "Visa Dup"})
    credit_accounts.update(dup["_id"], {"status": "Closed"})
    r, body = _create(store_client, credit_payload(name="Visa Dup"))
    assert r.status_code == 200 and body["ok"]


def test_duplicate_against_existing_account_card(store_client):
    # conftest seeds an active "Checking" account
    r, body = _create(store_client, {"Account Kind": "Bank/cash", "Account": "checking",
                                     "Amount": "1"})
    assert r.status_code == 400 and "already exists" in body["error"]


def test_stray_detail_record_replaced_on_retry(store_client):
    # a holding whose account card never landed (failed fan-out) is a stray:
    dbhelper.seed(portfolio, [
        {"_id": "stray1", "Asset": "NVDA", "Shares": "5",
         "Current Value": "$100.00", "account_id": "MAN-GONE"}])
    r, body = _create(store_client, stock_payload(ticker="NVDA", shares="5", price="500"))
    assert r.status_code == 200 and body["ok"]
    holdings = portfolio.list({"Asset": "NVDA"})
    assert len(holdings) == 1 and holdings[0]["_id"] != "stray1"
    audit = deletions.one({"collection": PORTFOLIO})
    assert audit and audit["doc"]["_id"] == "stray1"   # audited, per ADR-0005


def test_legacy_unlinked_holding_blocks_stock_create(store_client):
    # legacy holdings (no account_id) are duplicates, not strays — no backfill (R9)
    dbhelper.seed(portfolio, [{"_id": "legacy1", "Asset": "TSLA", "Shares": "2"}])
    r, body = _create(store_client, stock_payload(ticker="TSLA"))
    assert r.status_code == 400 and "already exists" in body["error"]
    assert portfolio.get("legacy1")


def test_smuggled_field_stripped_per_type(store_client):
    # a credit field smuggled into a stock create is dropped by the type allowlist
    p = stock_payload(ticker="AMD")
    p["Credit Limit"] = "9,999"
    r, body = _create(store_client, p)
    assert body["ok"]
    card = accounts.one({"Account": "AMD"})
    assert card.get("Credit Limit") is None


# --- derive-at-read + linked-card locks (U4) ---------------------------------------

def test_stock_card_value_derives_from_holding(store_client):
    r, body = _create(store_client, stock_payload(ticker="AAPL", price="1,500"))
    assert body["ok"]
    # edit the holding directly (as the Investments page would) — no push involved
    portfolio.update_where({"Asset": "AAPL"}, {"Current Value": 2000.0})
    page = (store_client.get("/accounts")).text
    assert "$2,000" in page
    # stored Amount was never touched — display derives at render
    card = accounts.one({"Account": "AAPL"})
    assert card["Amount"] == 1500.0


def test_credit_card_value_derives_from_newest_snapshot_by_name(store_client):
    from datetime import UTC, datetime, timedelta

    r, body = _create(store_client, credit_payload(name="Amex Gold", opening="500"))
    assert body["ok"]
    # a grid-added row: joined by NAME, carries no Account ID — must still surface
    dbhelper.seed(balance_history, [
        {"_id": "grid1", "Account": "Amex Gold", "Balance": -900.0,
         "Date": datetime.now(UTC) + timedelta(minutes=1), "_src": "manual"}])
    page = (store_client.get("/accounts")).text
    assert "-$900" in page


def test_linked_card_type_owned_fields_locked(store_client):
    r, body = _create(store_client, stock_payload(ticker="NFLX"))
    card_id = body["id"]
    r = store_client.post(f"/api/accounts/{card_id}", json={"Account": "Netflix"})
    assert r.status_code == 400 and "Investments" in r.json()["error"]
    r = store_client.post(f"/api/accounts/{card_id}", json={"Amount": "9,999"})
    assert r.status_code == 400
    r = store_client.post(f"/api/accounts/{card_id}", json={"Usage Notes": "long hold"})
    assert r.status_code == 200 and r.json()["ok"]


def test_bank_card_amount_still_editable(store_client):
    r, body = _create(store_client, {"Account Kind": "Bank/cash", "Account": "BoA",
                                     "Amount": "100"})
    r = store_client.post(f"/api/accounts/{body['id']}", json={"Amount": "250"})
    assert r.status_code == 200
    card = accounts.one({"Account": "BoA"})
    assert card["Amount"] == 250.0


# --- archive / reopen lifecycle (U5, AE4) -------------------------------------------

def test_archive_stock_closes_both_sides_and_keeps_history(store_client):
    r, body = _create(store_client, stock_payload(ticker="AAPL"))
    card_id = body["id"]
    before = balance_history.count({"Account": "AAPL"})

    r = store_client.post("/api/accounts/archive", json={"id": card_id})
    assert r.json() == {"ok": True, "status": "Closed"}

    card = accounts.get(card_id)
    assert card["Status"] == "Closed"
    holding = portfolio.one({"Asset": "AAPL"})
    assert holding["_closed"] is True

    # AE4: hidden from active views, skipped by refresh and sync, history intact
    assert "AAPL" not in (store_client.get("/accounts")).text
    assert "AAPL" in (store_client.get("/accounts?status=closed")).text
    assert "AAPL" not in (store_client.get("/investments")).text
    from app import investments as inv
    res = inv.refresh_prices(price_fn=lambda syms: {s: 1.0 for s in syms})
    assert res["updated"] == 0
    sync = (store_client.post("/api/investments/sync")).json()
    assert "AAPL" not in sync["accounts"]
    assert balance_history.count({"Account": "AAPL"}) == before


def test_reopen_restores_both_sides(store_client):
    r, body = _create(store_client, stock_payload(ticker="AMZN", shares="3", price="600"))
    store_client.post("/api/accounts/archive", json={"id": body["id"]})
    r = store_client.post("/api/accounts/reopen", json={"id": body["id"]})
    assert r.json()["ok"]
    card = accounts.get(body["id"])
    assert card["Status"] == "Active"
    holding = portfolio.one({"Asset": "AMZN"})
    assert not holding.get("_closed")
    sync = (store_client.post("/api/investments/sync")).json()
    assert "AMZN" in sync["accounts"]                 # tracking resumed


def test_archive_credit_drops_from_credit_page(store_client):
    r, body = _create(store_client, credit_payload(name="Chase Sapphire"))
    from app import credit as cr
    assert any(a["name"] == "Chase Sapphire" for a in cr.list_accounts())

    store_client.post("/api/accounts/archive", json={"id": body["id"]})
    entry = credit_accounts.one({"name": "Chase Sapphire"})
    assert entry["status"] == "Closed"
    assert not any(a["name"] == "Chase Sapphire" for a in cr.list_accounts())
    assert any(a["name"] == "Chase Sapphire"
               for a in cr.list_accounts(include_closed=True))


def test_unlinked_card_hard_delete_still_works(store_client):
    r, body = _create(store_client, {"Account Kind": "Bank/cash", "Account": "Old Bank",
                                     "Amount": "5"})
    r = store_client.post("/api/accounts/delete", json={"ids": [body["id"]]})
    assert r.json() == {"ok": True, "deleted": 1}
    snap = deletions.one({"collection": "accounts"})
    assert snap is not None                           # audited, per ADR-0005


# --- acceptance examples — one named test per AE (U6) --------------------------------

def test_ae1_price_refresh_flows_to_card_display(store_client):
    from app import investments as inv

    _create(store_client, stock_payload(ticker="AAPL", shares="10", price="1,000"))
    res = inv.refresh_prices(price_fn=lambda syms: {s: 250.0 for s in syms})
    assert res["updated"] == 1
    holding = portfolio.one({"Asset": "AAPL"})
    assert holding["Current Value"] == 2500.0
    assert "$2,500" in (store_client.get("/accounts")).text   # derived at render
    card = accounts.one({"Account": "AAPL"})
    r = store_client.post(f"/api/accounts/{card['_id']}", json={"Amount": "1"})
    assert r.status_code == 400                                # no editable amount


def test_ae2_credit_page_shows_limit_and_utilization(store_client):
    from app import credit as cr

    _create(store_client, credit_payload(name="Amex Blue", limit="5,000", opening="1,000"))
    acct = next(a for a in cr.list_accounts() if a["name"] == "Amex Blue")
    assert acct["credit_limit"] == 5000.0
    assert acct["balance"] == 1000.0        # from the creation snapshot
    assert acct["utilization"] == 0.2


def test_ae3_bank_account_on_balance_sheet_without_stamp(store_client):
    from datetime import datetime

    _create(store_client, {"Account Kind": "Bank/cash", "Account": "AE3 Bank",
                           "Institution": "Ally", "Amount": "77"})
    now = datetime.now()
    page = (store_client.get(f"/balance-sheet?year={now.year}&month={now.month}")).text
    assert "AE3 Bank" in page and "Ally" in page


def test_ae4_archived_stock_keeps_prior_month_balance_sheet(store_client):
    from datetime import UTC, datetime

    r, body = _create(store_client, stock_payload(ticker="AAPL", price="1,500"))
    # a recorded value in a prior month
    prior = datetime(2026, 6, 15, tzinfo=UTC)
    dbhelper.seed(balance_history, [
        {"_id": "prior1", "Account": "AAPL", "Balance": 1400.0, "Class": "Equity",
         "Date": prior, "_src": "portfolio_sync"}])
    store_client.post("/api/accounts/archive", json={"id": body["id"]})

    assert "AAPL" not in (store_client.get("/accounts")).text
    assert "AAPL" not in (store_client.get("/investments")).text
    assert "AAPL" in (store_client.get("/balance-sheet?year=2026&month=6")).text


def test_ae5_sync_in_creation_month_still_appends(store_client):
    _create(store_client, stock_payload(ticker="AAPL", shares="10", price="1,500"))
    sync = (store_client.post("/api/investments/sync")).json()
    assert "AAPL" in sync["accounts"] and "AAPL" not in sync["skipped"]
    assert balance_history.count({"Account": "AAPL", "_src": "portfolio_sync"}) == 1


def test_ae6_archived_name_recreatable_active_rejected(store_client):
    r, body = _create(store_client, credit_payload(name="Visa X"))
    r2, b2 = _create(store_client, credit_payload(name="Visa X"))
    assert r2.status_code == 400 and "already exists" in b2["error"]
    store_client.post("/api/accounts/archive", json={"id": body["id"]})
    r3, b3 = _create(store_client, credit_payload(name="Visa X"))
    assert r3.status_code == 200 and b3["ok"]


def test_failed_fanout_leaves_no_card(store_client):
    # invalid ticker fails validation before any write
    r, _ = _create(store_client, {"Account Kind": "Common stock", "Ticker": "",
                                  "Shares": "1", "Purchase Price": "10"})
    assert r.status_code == 400
    assert accounts.one({"Account Kind": "Common stock"}) is None


# --- editable investments: linked-card propagation (plan 002, AE1) ------------------

def test_ae1_holding_edit_flows_to_both_pages_without_refresh(store_client):
    from app import investments as inv

    # fan-out-created stock, refreshed once to $250/share
    r, body = _create(store_client, stock_payload(ticker="AAPL", shares="10",
                                                  price="2,000"))
    assert body["ok"]
    res = inv.refresh_prices(price_fn=lambda syms: {"AAPL": 250.0})
    assert res["updated"] == 1

    holding = portfolio.one({"Asset": "AAPL"})
    r = store_client.post(f"/api/investments/holding/{holding['_id']}",
                          json={"Shares": "12"})
    assert r.status_code == 200 and r.json()["ok"]

    # both pages show 12 × $250 = $3,000 before any price refresh runs
    assert "$3,000.00" in (store_client.get("/investments")).text
    assert "$3,000" in (store_client.get("/accounts")).text


def test_legacy_holding_edit_updates_page_but_name_matched_card_lags(store_client):
    # A legacy (unlinked) holding edits identically on the Investments page. Its
    # name-matched Accounts card is refresh-owned, so it lags the edit until the
    # next refresh — the two-regimes rule (plan 001 R9).
    dbhelper.seed(portfolio, [
        {"_id": "leg1", "Asset": "MSFT", "Account": "Brokerage", "Shares": "10",
         "Purchase Price": "$2,000.00", "Current Price": "$250.00",
         "Current Value": "$2,500.00"}])
    dbhelper.seed(accounts, [
        {"_id": "a-leg", "Account ID": "L1", "Account": "MSFT", "Type": "Equity",
         "Amount": 2500.0, "Status": "Open"}])

    r = store_client.post("/api/investments/holding/leg1", json={"Shares": "12"})
    assert r.status_code == 200
    assert "$3,000.00" in (store_client.get("/investments")).text
    card = accounts.get("a-leg")
    assert card["Amount"] == 2500.0            # stale until the next refresh — by design
