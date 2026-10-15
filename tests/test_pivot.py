"""Pivot tabulation — the report maths that used to be reachable only by rendering a
full page against Mongo. Now pure: hand-written rows in, ordered sections out."""

from app.pivot import ordered, pivot


def test_ordered_canonical_first_then_rest_in_seen_order():
    # preferred labels that are present come first (in preferred order); the rest follow
    # in first-seen order. Absent preferred labels (Transfer) are dropped.
    assert ordered(["Expense", "Weird", "Income"],
                   ["Income", "Transfer", "Expense"]) == ["Income", "Expense", "Weird"]


def test_pnl_shape_orders_sections_sorts_rows_and_sums():
    months = [1, 2]
    rows = [
        {"type": "Expense", "group": "Food", "by_month": {1: -100.0, 2: -50.0}, "total": -150.0},
        {"type": "Expense", "group": "Rent", "by_month": {1: -2000.0}, "total": -2000.0},
        {"type": "Income", "group": "Salary", "by_month": {1: 5000.0, 2: 5000.0}, "total": 10000.0},
    ]
    table = pivot(rows, columns=months,
                  section_of=lambda r: r["type"],
                  values_of=lambda r: r["by_month"],
                  sort_of=lambda r: r["total"],
                  section_order=["Income", "Transfer", "Expense"])

    # Income before Expense (canonical order), Transfer dropped (no rows).
    assert [s["label"] for s in table["sections"]] == ["Income", "Expense"]

    income, expense = table["sections"]
    assert [r["group"] for r in income["rows"]] == ["Salary"]
    # rows sort by |total| desc — Rent (2000) before Food (150)
    assert [r["group"] for r in expense["rows"]] == ["Rent", "Food"]

    # per-column subtotals, missing months count as 0
    assert expense["subtotals"] == {1: -2100.0, 2: -50.0}
    assert income["subtotals"] == {1: 5000.0, 2: 5000.0}

    # section subtotal == sum of row totals
    assert income["subtotal"] == 10000.0
    assert expense["subtotal"] == -2150.0

    # column totals across sections, and grand
    assert table["totals"] == {1: 2900.0, 2: 4950.0}
    assert table["grand"] == 7850.0


def test_balance_sheet_shape_subtotals_each_measure():
    measures = ["starting", "ending", "maxb"]
    rows = [
        {"cls": "Assets", "account": "Checking", "starting": 100.0, "ending": 150.0, "maxb": 200.0},
        {"cls": "Assets", "account": "Savings", "starting": 1000.0, "ending": 900.0, "maxb": 1100.0},
        {"cls": "Liabilities", "account": "Visa", "starting": -50.0, "ending": -80.0, "maxb": -30.0},
    ]
    table = pivot(rows, columns=measures,
                  section_of=lambda r: r["cls"],
                  values_of=lambda r: {k: r[k] for k in measures},
                  sort_of=lambda r: r["ending"],
                  section_order=["Assets", "Equity", "Liabilities"])

    assert [s["label"] for s in table["sections"]] == ["Assets", "Liabilities"]
    assets = table["sections"][0]
    # sorted by |ending| desc — Savings (900) before Checking (150)
    assert [r["account"] for r in assets["rows"]] == ["Savings", "Checking"]
    assert assets["subtotals"] == {"starting": 1100.0, "ending": 1050.0, "maxb": 1300.0}


def test_empty_rows_yield_no_sections():
    table = pivot([], columns=[1], section_of=lambda r: r["t"],
                  values_of=lambda r: {}, sort_of=lambda r: 0)
    assert table["sections"] == [] and table["grand"] == 0.0 and table["totals"] == {1: 0.0}
