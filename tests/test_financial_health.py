"""Financial Health Analysis — compute() must reproduce the workbook's exact values for the
FY 2025 inputs (ratios + the seven composite scores, including the negative ones)."""

from app import financial_health as hm

# The blue-cell inputs from "Financial Health Metrics (1).xlsx" → Financial Health Analysis.
FY2025 = {
    "cash": 95000, "non_current_assets": 725967, "short_term_debt": 700,
    "revenue": 2000, "operating_expenses": 4000,
    "operating_cash_flow": 2000, "capex": 2000, "total_operating_expenses": 4000,
}


def test_calc_subtotals_match_sheet():
    c = hm.compute(FY2025)["calc"]
    assert c["total_assets"] == 820967.0
    assert c["total_equity"] == 820267.0
    assert c["ebit"] == -2000.0
    assert c["net_income"] == -2000.0
    assert c["free_cash_flow"] == 0.0


def test_ratios_match_sheet():
    ratios = {r["name"]: r["value"] for r in hm.compute(FY2025)["ratios"]}
    assert ratios["Current Ratio"] == 135.7143
    assert ratios["Working Capital"] == 94300.0
    assert ratios["Net Margin"] == -1
    assert ratios["Debt-to-EBITDA"] == -0.35
    assert ratios["Equity Ratio"] == 0.9991
    assert ratios["Interest Coverage"] is None     # interest expense 0 → N/A
    assert ratios["Cash Runway (months)"] is None  # no monthly burn → N/A


def test_composite_scores_match_sheet():
    comps = {c["name"]: c["score"] for c in hm.compute(FY2025)["composites"]}
    assert comps["Financial Resilience"] == 50
    assert comps["Fragility Under Stress"] == 0
    assert comps["Ability to Self-Fund Growth"] == -151    # negatives are preserved
    assert comps["Dependence on Outside Capital"] == 15
    assert comps["Earnings Quality"] == -138
    assert comps["Spending Sustainability"] == -130
    assert comps["Surplus Reality Check"] == -5


def test_rating_tiers_and_inversion():
    comps = {c["name"]: c["rating"] for c in hm.compute(FY2025)["composites"]}
    assert comps["Financial Resilience"]["emoji"] == "⚠️"   # 50 → moderate
    assert comps["Fragility Under Stress"]["emoji"] == "✅"  # 0, inverted → low risk
    assert comps["Dependence on Outside Capital"]["emoji"] == "✅"  # 15, inverted → low


def test_empty_inputs_are_na():
    c = hm.compute({})
    assert all(x["score"] is None for x in c["composites"])
    assert c["calc"]["total_assets"] == 0.0


def test_input_sections_carry_help_text(store_client):
    # Every input field has a tooltip definition.
    for _section, fields in hm.INPUT_SECTIONS:
        for key, label, help in fields:
            assert key and label and help and len(help) > 10
    r = store_client.get("/health-analysis")
    assert "Hover any field label" in r.text


def test_save_and_render(store_client):
    res = hm.save_period({"period": "FY 2025", **{k: str(v) for k, v in FY2025.items()}})
    pid = res["id"]
    # idempotent upsert by name
    res2 = hm.save_period({"period": "FY 2025", **FY2025})
    assert res2["id"] == pid

    r = store_client.get("/health-analysis?period=" + pid)
    assert r.status_code == 200
    assert "Composite judgments" in r.text and "Financial Resilience" in r.text
    # the newest period is the default, and delete audits it away
    assert (hm.get_period(None))["id"] == pid
    assert (hm.get_period(pid))["inputs"]["cash"] == 95000.0
    assert hm.delete_period({"id": pid}) == {"ok": True, "deleted": 1}
    assert hm.list_periods() == []
