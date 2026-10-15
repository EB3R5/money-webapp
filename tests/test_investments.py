"""Investments — portfolio parsing, price refresh (stubbed quotes, no network),
and the idempotent sync into balanceHistory."""

from app import investments as inv
from app.store.accounts import accounts
from app.store.balance_history import balance_history
from app.store.portfolio import portfolio
from tests import dbhelper


def test_ticker_and_mapping_rules():
    assert inv.normalize_ticker("BRK.B") == "BRK-B"
    assert inv.normalize_ticker("Cash Sweep") is None       # cash → no quote
    assert inv.normalize_ticker("xyz") == "XYZ"
    assert inv.map_group("Equity") == "Stockholder's Equity"
    assert inv.map_type("Individual Stock") == "Equity"
    assert inv.map_type("Cash") == "Assets"
    assert inv.money(-3605.29) == "-$3,605.29"


def test_portfolio_rows_skips_totals_and_computes_return():
    holdings = [
        {"Asset": "XYZ", "Shares": "150", "Purchase Price": "$5,162.29",
         "Current Price": "$10.38", "Current Value": "$1,557.00", "Account": "Brokerage"},
        {"Asset": "", "Current Value": "$822,046.65"},      # trailing totals row → skipped
    ]
    rows, total = inv.portfolio_rows(holdings)
    assert len(rows) == 1
    r = rows[0]
    assert r["asset"] == "XYZ" and r["value"] == 1557.0
    assert round(r["ret"], 2) == round(1557.00 - 5162.29, 2)   # loss
    assert total["value"] == 1557.0


def _seed_portfolio(client=None):
    dbhelper.seed(portfolio, [
        {"_id": "p1", "Asset": "BRK.B", "Account": "Brokerage", "Group": "Equity",
         "Type": "Individual Stock", "Category": "Common Stock",
         "Shares": "200", "Purchase Price": "$80,000.00",
         "Current Price": "$489.46", "Current Value": "$97,892.00"},
        {"_id": "p2", "Asset": "Cash Sweep", "Account": "Brokerage", "Shares": "1000",
         "Current Value": "$1,000.00"},
        {"_id": "p3", "Asset": "", "Current Value": "$98,892.00"},   # totals row
    ])


def test_refresh_prices_updates_value_from_quote(store_client):
    _seed_portfolio()
    # Stub the quote source — BRK.B normalizes to BRK-B; cash is never requested.
    fake = {"BRK-B": 500.0}

    def price_fn(symbols):
        assert symbols == ["BRK-B"]                          # cash + totals excluded
        return fake

    res = inv.refresh_prices(price_fn=price_fn)
    assert res["updated"] == 1 and res["failed"] == []
    doc = portfolio.get("p1")
    assert doc["Current Price"] == 500.0
    assert doc["Current Value"] == 100000.0                  # 200 × 500
    assert doc["Return"] == 20000.0                          # 100k − 80k cost


def test_refresh_syncs_matching_account_amount(store_client):
    # Accounts page reads accounts.Amount; refresh must propagate the live value
    # to the account whose Account == the holding's ticker (bug #1).
    _seed_portfolio()
    dbhelper.seed(accounts, [
        {"_id": "a1", "Account": "BRK.B", "Type": "Equity", "Amount": 94416.0}])

    res = inv.refresh_prices(price_fn=lambda syms: {"BRK-B": 500.0})
    assert res["accounts_synced"] == 1
    acct = accounts.get("a1")
    assert acct["Amount"] == 100000.0                        # 200 × 500, not stale


def test_refresh_reports_missing_quote(store_client):
    _seed_portfolio()
    res = inv.refresh_prices(price_fn=lambda syms: {})   # no quotes returned
    assert res["updated"] == 0 and res["failed"] == ["BRK.B"]


def test_sync_ports_holdings_as_equity_and_appends_records(store_client):
    _seed_portfolio()
    r = store_client.post("/api/investments/sync")
    body = r.json()
    assert body["ok"] and "BRK.B" in body["accounts"]

    stock = balance_history.one({"Account": "BRK.B", "_src": "portfolio_sync"})
    assert stock["Type"] == "Equity" and stock["Class"] == "Equity"
    assert stock["Group"] == "Stockholder's Equity" and stock["Balance"] == 97892.0
    cash = balance_history.one({"Account": "Cash Sweep", "_src": "portfolio_sync"})
    assert cash["Type"] == "Assets" and cash["Category"] == "Cash & Equivalents"
    assert cash["Account Type"] == "Cash & Equivalents" and cash.get("Account #") is None

    # re-sync appends new dated records — earlier snapshots stay as history
    before = balance_history.count({"_src": "portfolio_sync"})
    store_client.post("/api/investments/sync")
    assert balance_history.count({"_src": "portfolio_sync"}) == before * 2


def test_sync_skips_accounts_with_manual_balance_this_month(store_client):
    from datetime import date, datetime, timedelta

    _seed_portfolio()
    # BRK.B already has a manual balance this month; Cash Sweep has one from last month.
    this_month = datetime.combine(date.today().replace(day=1), datetime.min.time())
    dbhelper.seed(balance_history, [
        {"_id": "man_1", "Account": "BRK.B", "Balance": 90000.0,
         "Date": this_month, "_src": "manual"},
        {"_id": "man_2", "Account": "Cash Sweep", "Balance": 500.0,
         "Date": this_month - timedelta(days=1), "_src": "manual"},
    ])

    r = store_client.post("/api/investments/sync")
    body = r.json()
    assert body["ok"] and body["skipped"] == ["BRK.B"]
    assert "BRK.B" not in body["accounts"] and "Cash Sweep" in body["accounts"]

    # The manual row stays authoritative; no portfolio record was written for BRK.B.
    assert balance_history.count({"Account": "BRK.B", "_src": "portfolio_sync"}) == 0
    manual = balance_history.get("man_1")
    assert manual["Balance"] == 90000.0

    # Earlier synced records for a now-skipped account survive untouched.
    balance_history.delete_where(_src="manual")
    store_client.post("/api/investments/sync")           # BRK.B recorded normally again
    dbhelper.seed(balance_history, [
        {"_id": "man_3", "Account": "BRK.B", "Balance": 91000.0,
         "Date": this_month, "_src": "manual"}])
    r = store_client.post("/api/investments/sync")
    assert r.json()["skipped"] == ["BRK.B"]
    assert balance_history.count({"Account": "BRK.B", "_src": "portfolio_sync"}) == 1   # no new record while skipped


def test_sync_ignores_creation_snapshots_and_carries_linked_id(store_client):
    from datetime import UTC, datetime

    _seed_portfolio()
    # link BRK.B to a card, as the Add-account fan-out would
    portfolio.update_where({"Asset": "BRK.B"}, {"account_id": "MAN-LINKED1"})
    # AE5: a creation snapshot this month does NOT freeze the ticker out of the sync
    dbhelper.seed(balance_history, [
        {"_id": "create1", "Account": "BRK.B", "Balance": 97892.0,
         "Date": datetime.now(UTC), "_src": "account_create"}])
    r = store_client.post("/api/investments/sync")
    body = r.json()
    assert body["ok"] and "BRK.B" in body["accounts"] and body["skipped"] == []

    row = balance_history.one({"Account": "BRK.B", "_src": "portfolio_sync"})
    assert row["Account ID"] == "MAN-LINKED1"        # linked card's ID, not the hash
    legacy = balance_history.one({"Account": "Cash Sweep", "_src": "portfolio_sync"})
    assert len(legacy["Account ID"]) == 24            # legacy holdings keep the sha id


# --- position-fact edits (editable investments) ------------------------------

def test_edit_shares_recomputes_value_at_last_known_price(store_client):
    dbhelper.seed(portfolio, [
        {"_id": "e1", "Asset": "SNOW", "Account": "Brokerage", "Shares": "10",
         "Purchase Price": "$2,000.00", "Current Price": "$250.00",
         "Current Value": "$2,500.00"}])
    r = store_client.post("/api/investments/holding/e1", json={"Shares": "12"})
    assert r.status_code == 200 and r.json()["ok"]
    doc = portfolio.get("e1")
    assert doc["Shares"] == 12.0
    assert doc["Current Value"] == 3000.0                    # 12 × $250, no refresh
    assert doc["Return"] == 1000.0                           # 3,000 − 2,000 cost
    assert doc["Delta"] == 0.5
    assert round(doc["Avg Cost"], 2) == 166.67               # 2,000 ÷ 12


def test_edit_purchase_price_recomputes_return_not_value(store_client):
    _seed_portfolio()
    r = store_client.post("/api/investments/holding/p1",
                          json={"Purchase Price": "90000"})
    assert r.status_code == 200
    doc = portfolio.get("p1")
    assert doc["Purchase Price"] == 90000.0
    assert doc["Current Value"] == 97892.0                   # 200 × $489.46 — unchanged
    assert doc["Return"] == 7892.0
    assert doc["Avg Cost"] == 450.0                          # 90,000 ÷ 200


def test_edit_brokerage_updates_account_and_nothing_else(store_client):
    _seed_portfolio()
    r = store_client.post("/api/investments/holding/p1", json={"Brokerage": "Schwab"})
    assert r.status_code == 200
    doc = portfolio.get("p1")
    assert doc["Account"] == "Schwab"
    assert doc["Current Value"] == 97892.0                   # money fields untouched
    assert doc["Purchase Price"] == 80000.0
    assert doc.get("Avg Cost") is None and doc.get("Return") is None


def test_edit_shares_on_never_refreshed_holding_uses_cost_basis(store_client):
    dbhelper.seed(portfolio, [
        {"_id": "e2", "Asset": "NEWCO", "Account": "Brokerage", "Shares": "10",
         "Purchase Price": "$1,000.00"}])                    # no Current Price/Value yet
    r = store_client.post("/api/investments/holding/e2", json={"Shares": "12"})
    assert r.status_code == 200
    doc = portfolio.get("e2")
    assert doc["Current Value"] == 1200.0                    # $100/share from purchase ÷ 10


def test_edit_cash_shares_derives_price_from_existing_value(store_client):
    _seed_portfolio()                            # p2: cash, 1000 sh, $1,000
    r = store_client.post("/api/investments/holding/p2", json={"Shares": "1200"})
    assert r.status_code == 200
    doc = portfolio.get("p2")
    assert doc["Current Value"] == 1200.0                    # $1/share — never $0


def test_edit_rejects_bad_values_and_bad_targets(store_client):
    _seed_portfolio()
    portfolio.update("p2", {"_closed": True})
    for payload in [{"Shares": "abc"}, {"Shares": "0"}, {"Shares": "-5"},
                    {"Purchase Price": "garbage"}, {}]:
        r = store_client.post("/api/investments/holding/p1", json=payload)
        assert r.status_code == 400, payload
    assert (store_client.post("/api/investments/holding/nope",
                              json={"Shares": "1"})).status_code == 404
    assert (store_client.post("/api/investments/holding/p2",
                              json={"Shares": "1"})).status_code == 400  # archived
    doc = portfolio.get("p1")
    assert doc["Shares"] == 200.0                            # nothing written


def test_edit_ignores_fields_outside_the_whitelist(store_client):
    _seed_portfolio()
    r = store_client.post("/api/investments/holding/p1", json={
        "Shares": "100", "Asset": "HACK", "Current Price": "$1.00", "_closed": True})
    assert r.status_code == 200
    doc = portfolio.get("p1")
    assert doc["Asset"] == "BRK.B" and doc["Current Price"] == 489.46
    assert not doc.get("_closed")
    assert doc["Shares"] == 100.0                            # whitelisted edit applied
    r = store_client.post("/api/investments/holding/p1", json={"Asset": "HACK"})
    assert r.status_code == 400                              # nothing editable → rejected


def test_sync_after_edit_records_the_recomputed_value(store_client):
    _seed_portfolio()
    r = store_client.post("/api/investments/holding/p1", json={"Shares": "100"})
    assert r.status_code == 200
    store_client.post("/api/investments/sync")
    snap = balance_history.one({"Account": "BRK.B", "_src": "portfolio_sync"})
    assert snap["Balance"] == 48946.0                        # 100 × $489.46, post-edit


def test_investments_page_renders(store_client):
    _seed_portfolio()
    r = store_client.get("/investments")
    assert r.status_code == 200
    assert "BRK.B" in r.text and "Refresh prices" in r.text


def test_investments_rows_are_editable_targets(store_client):
    _seed_portfolio()
    dbhelper.seed(portfolio, [
        {"_id": "p9", "Asset": "GONE", "Shares": "5", "_closed": True}])
    r = store_client.get("/investments")
    html = r.text
    assert 'data-id="p1"' in html and 'data-id="p2"' in html
    assert html.count('data-id="') == 2          # totals row and tfoot carry none
    assert "GONE" not in html                    # archived holdings stay hidden
    # The modal offers exactly the three position facts, nothing else.
    assert 'name="Shares"' in html and 'name="Purchase Price"' in html
    assert 'name="Brokerage"' in html
    assert 'name="Current Price"' not in html and 'name="Asset"' not in html
    assert "makeCardEditor" in html and "/api/investments/holding" in html
