"""Report PNG export — every server-rendered report exposes a ⬇ PNG button wired to the
report-png.js helper (the actual capture is client-side via html-to-image)."""

import pytest

# (path, expected data-png-target) for each report that should offer a PNG download.
REPORTS = [
    ("/pnl", "table.pivot"),
    ("/balance-sheet", "table.pivot"),
    ("/budgets/pivot", "table.bva-pivot"),
    ("/inventory-overview", "table.pivot"),
    ("/category-insights", ".ci-panels"),
]


@pytest.mark.parametrize("path,target", REPORTS)
def test_report_has_png_button(store_client, path, target):
    if path == "/balance-sheet":
        # The button only renders when there is a month to capture.
        from tests import dbhelper
        dbhelper.seed_balances()
    if path == "/budgets/pivot":
        # The button only renders when there is a budget to capture.
        from app.store.budget_lines import budget_lines
        from app.store.budgets import budgets
        budgets.insert({"_id": "bud_a", "budgetId": "BUD001", "versionName": "Baseline",
                              "month": "2026-01"})
        budget_lines.insert({"budget": "bud_a", "position": 0, "group": "Food", "amount": 100})
    html = (store_client.get(path)).text
    assert 'data-png-target="' + target + '"' in html
    assert "report-png.js" in html and "html-to-image" in html
