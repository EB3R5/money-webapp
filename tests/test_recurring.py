"""Recurring series (app/recurring.py, ADR-0021 D5): merchant normalisation, cadence
bands, the ended / too-few rules, next-date projection, per-month arithmetic, occurrences in
a month, and the two loaders over seeded transactions and categories."""

from datetime import date, datetime, timedelta

from app import recurring
from app.store.categories import categories
from app.store.transactions import transactions
from tests import dbhelper

TODAY = date(2026, 10, 5)


def _rows(key, days, amount, label=None, category=None):
    return [{"date": d, "amount": amount, "key": key, "label": label or key,
             "category": category or key} for d in days]


def _every(start, step, n):
    return [start + timedelta(days=step * i) for i in range(n)]


def test_normalize_merchant_folds_paypal_web_id_and_masks():
    a = recurring.normalize_merchant("PAYPAL PURCHASE Spotify web id: 12345")
    b = recurring.normalize_merchant("PAYPAL INST XFER   Spotify WEB ID: 999")
    assert a == b == "spotify"
    assert recurring.normalize_merchant("Chase Card xxxx1234 Netflix 09/21") == "chase card netflix"
    assert recurring.normalize_merchant("ALLY AUTO XXXX 4421 PMT") == "ally auto pmt"
    assert recurring.normalize_merchant("") == "" and recurring.normalize_merchant(None) == ""


def test_cadence_bands():
    assert recurring.cadence_of([7, 7, 8]) == ("weekly", 7.0)
    assert recurring.cadence_of([14, 14, 15]) == ("biweekly", 14.0)
    assert recurring.cadence_of([30, 31, 29]) == ("monthly", 30.44)
    assert recurring.cadence_of([91, 92]) == ("quarterly", 91.3)
    assert recurring.cadence_of([182]) == ("semiyearly", 182.6)
    assert recurring.cadence_of([365]) == ("yearly", 365.25)
    assert recurring.cadence_of([3, 50, 200]) is None          # median 50: no band
    assert recurring.cadence_of([]) is None


def test_detect_monthly_series_amount_next_date_and_per_month():
    days = [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]
    rows = _rows("Rent", days, -1200.0) + [{"date": date(2026, 9, 1), "amount": -17.0,
                                              "key": "Rent", "label": "Rent", "category": "Rent"}]
    [s] = recurring.detect(rows, today=TODAY)
    assert s["cadence"] == "monthly" and s["period_days"] == 30.44
    assert s["count"] == 3                                       # same-day rows merge
    assert s["amount"] == 1200.0                                 # median of |1200|, |1200|, |1217|
    assert s["last_date"] == "2026-09-01" and s["next_date"] == "2026-10-01" or s["next_date"] == "2026-10-31"
    assert s["expected_count"] == 3.0 and s["confidence"] == 1.0
    assert s["per_month"] == 1200.0


def test_detect_next_date_is_advanced_to_today_or_later():
    days = _every(date(2026, 1, 2), 14, 10)                      # biweekly, last 2026-05-08
    [s] = recurring.detect(_rows("Pay", days, 1500.0), today=date(2026, 5, 20))
    assert s["cadence"] == "biweekly" and s["next_date"] == "2026-05-22"
    assert s["per_month"] == round(1500 * 30.44 / 14, 2)


def test_detect_drops_ended_and_too_few_series():
    old = _every(date(2025, 1, 1), 30, 6)                        # monthly, ended in June 2025
    few = [date(2026, 8, 1), date(2026, 9, 1)]                   # monthly but only 2 points
    yearly = [date(2024, 11, 1), date(2025, 11, 1)]              # 2 points is enough when slow
    rows = _rows("Old", old, -50.0) + _rows("Few", few, -50.0) + _rows("Annual", yearly, -300.0)
    out = {s["key"]: s for s in recurring.detect(rows, today=TODAY, lookback_days=1000)}
    assert set(out) == {"Annual"}
    assert out["Annual"]["cadence"] == "yearly" and out["Annual"]["next_date"] == "2026-11-01"


def test_detect_irregular_series_is_kept_without_a_period():
    days = [date(2026, 1, 3), date(2026, 2, 20), date(2026, 6, 1), date(2026, 6, 25)]   # gaps 48, 101, 24
    [s] = recurring.detect(_rows("Gifts", days, 100.0), today=TODAY)
    assert s["cadence"] == "irregular" and s["period_days"] is None
    assert s["next_date"] is None and s["per_month"] is None and s["confidence"] is None


def test_detect_ignores_rows_outside_the_lookback_and_in_the_future():
    days = _every(date(2023, 1, 1), 30, 40)                      # every 30 days, last 2026-03-16
    today = date(2026, 4, 1)
    rows = _rows("S", days, 10.0) + _rows("S", [date(2027, 1, 1)], 10.0)
    [s] = recurring.detect(rows, today=today, lookback_days=365)
    assert s["last_date"] == (date(2023, 1, 1) + timedelta(days=30 * 39)).isoformat()
    assert s["count"] == sum(1 for d in days if d >= today - timedelta(days=365)) == 12


def test_detect_sorts_by_per_month_then_label():
    big = _rows("B", _every(date(2026, 7, 1), 30, 3), 500.0)
    small = _rows("A", _every(date(2026, 7, 1), 30, 3), 100.0)
    irregular = _rows("Z", [date(2026, 1, 1), date(2026, 3, 1), date(2026, 8, 1)], 9.0)
    assert [s["key"] for s in recurring.detect(small + big + irregular, today=TODAY)] == ["B", "A", "Z"]


def test_occurrences_in_month():
    biweekly = {"cadence": "biweekly", "period_days": 14.0, "last_date": "2026-09-25"}
    assert recurring.occurrences_in_month(biweekly, "2026-09") == 2
    assert recurring.occurrences_in_month(biweekly, "2026-10") == 2     # Oct 9, Oct 23
    assert recurring.occurrences_in_month(biweekly, "2026-05") == 2
    weekly = {"cadence": "weekly", "period_days": 7.0, "last_date": "2026-09-25"}
    assert recurring.occurrences_in_month(weekly, "2026-10") == 5       # Oct 2, 9, 16, 23, 30
    monthly = {"cadence": "monthly", "period_days": 30.44, "last_date": "2026-09-01"}
    assert recurring.occurrences_in_month(monthly, "2026-02") == 1
    quarterly = {"cadence": "quarterly", "period_days": 91.3, "last_date": "2026-09-15", "first_date": "2026-03-15"}
    assert recurring.occurrences_in_month(quarterly, "2026-06") == 1    # Jun 15, within the series
    assert recurring.occurrences_in_month(quarterly, "2025-12") == 0    # before it began
    assert recurring.occurrences_in_month(quarterly, "2026-12") == 1    # Dec 15
    assert recurring.occurrences_in_month(quarterly, "2026-11") == 0
    assert recurring.occurrences_in_month({"cadence": "irregular", "period_days": None}, "2026-10") == 0


def test_income_sources_loader_groups_by_category(store_db):
    dbhelper.seed(transactions, [
        {"_id": f"p{i}", "Date": datetime(2026, 7 + i, 15), "Category": "Salary", "Amount": 3000.0, "Type": "Income"}
        for i in range(3)
    ] + [
        {"_id": "pend", "Date": datetime(2026, 10, 1), "Category": "Salary", "Amount": 3000.0, "Type": "Income", "pending": True},
        {"_id": "exp", "Date": datetime(2026, 9, 1), "Category": "Salary", "Amount": -5.0, "Type": "Expense"},
        {"_id": "blank", "Date": datetime(2026, 9, 2), "Category": "", "Amount": 70.0, "Type": "Income"},
    ])
    [s] = recurring.income_sources(datetime(2026, 10, 5))
    assert s["key"] == s["label"] == s["category"] == "Salary"
    assert s["cadence"] == "monthly" and s["count"] == 3 and s["amount"] == 3000.0
    assert s["last_date"] == "2026-09-15"                        # the pending October row is not an occurrence


def test_bills_loader_uses_category_timing_and_merges_merchant_variants(store_db):
    dbhelper.seed(categories, [
        {"_id": "Streaming", "Category": "Streaming", "Group": "Fun", "Type": "Expense", "Timing": "Monthly"},
        {"_id": "Dining", "Category": "Dining", "Group": "Food", "Type": "Expense", "Timing": "One-Time"},
    ])
    dbhelper.seed(transactions, [
        {"_id": "s1", "Date": datetime(2026, 7, 3), "Description": "PAYPAL PURCHASE Spotify web id: 111",
         "Category": "Streaming", "Amount": -10.99, "Type": "Expense", "Timing": "Not Found"},
        {"_id": "s2", "Date": datetime(2026, 8, 3), "Description": "PAYPAL INST XFER Spotify web id: 222",
         "Category": "Streaming", "Amount": -10.99, "Type": "Expense", "Timing": "Not Found"},
        {"_id": "s3", "Date": datetime(2026, 9, 3), "Description": "PAYPAL PURCHASE Spotify web id: 333",
         "Category": "Streaming", "Amount": -11.99, "Type": "Expense"},
        {"_id": "d1", "Date": datetime(2026, 7, 9), "Description": "Taqueria", "Category": "Dining", "Amount": -20.0, "Type": "Expense"},
        {"_id": "d2", "Date": datetime(2026, 8, 9), "Description": "Taqueria", "Category": "Dining", "Amount": -20.0, "Type": "Expense"},
        {"_id": "d3", "Date": datetime(2026, 9, 9), "Description": "Taqueria", "Category": "Dining", "Amount": -20.0, "Type": "Expense"},
        {"_id": "r1", "Date": datetime(2026, 9, 4), "Description": "Spotify refund", "Category": "Streaming", "Amount": 5.0, "Type": "Expense"},
    ])
    [s] = recurring.bills(datetime(2026, 10, 5))           # Dining's Timing is One-Time: no series
    assert s["key"] == "spotify" and s["category"] == "Streaming"
    assert s["label"] == "PAYPAL PURCHASE Spotify web id: 333"   # the most recent description
    assert s["cadence"] == "monthly" and s["count"] == 3 and s["amount"] == 10.99


def test_bills_loader_drops_series_whose_amount_wanders(store_db):
    """A gas station visited weekly sits in a Weekly category, but it is variable spend,
    not a bill: the amount spread over the last three visits exceeds STABLE_SPREAD."""
    dbhelper.seed(categories, [
        {"_id": "Gas", "Category": "Gas", "Group": "Car", "Type": "Expense", "Timing": "Weekly"},
        {"_id": "Insurance", "Category": "Insurance", "Group": "Car", "Type": "Expense", "Timing": "Monthly"},
    ])
    rows = []
    for i, amt in enumerate([-31.0, -48.5, -22.0, -55.0, -40.0]):
        rows.append({"_id": f"g{i}", "Date": datetime(2026, 9, 1 + 7 * i), "Description": "CORNER MART #2979 SPRINGFIELD",
                     "Category": "Gas", "Amount": amt, "Type": "Expense"})
    for i in range(3):
        rows.append({"_id": f"i{i}", "Date": datetime(2026, 7 + i, 15), "Description": "GEICO AUTO",
                     "Category": "Insurance", "Amount": -180.0, "Type": "Expense"})
    dbhelper.seed(transactions, rows)
    today = datetime(2026, 10, 5)
    found = {s["key"]: s for s in recurring.detect(
        [{"date": r["Date"], "amount": r["Amount"], "key": r["Description"].split(" ")[0].lower(),
          "label": r["Description"], "category": r["Category"]} for r in rows], today=today)}
    assert found["corner"]["cadence"] == "weekly" and found["corner"]["stable"] is False
    assert found["geico"]["stable"] is True and found["geico"]["spread"] == 0.0
    [bill] = recurring.bills(today)
    assert bill["key"] == "geico auto" and bill["amount"] == 180.0
