"""Tax — config + mapping stored; income/deductions derived from transactions; federal/SE/state
calc and quarterly safe-harbor computed."""

from datetime import datetime

import pytest

from app import tax
from app.store.transactions import transactions
from app.web import DomainError
from tests import dbhelper

YEAR = 2027


def test_bracket_tax_pure():
    # 2025 single brackets on $95,000 taxable.
    t = tax._bracket_tax(95000, tax.BRACKETS["SINGLE"])
    assert round(t, 2) == 15814.0
    assert tax._marginal_rate(95000, tax.BRACKETS["SINGLE"]) == 0.22


def _seed():
    dbhelper.seed(transactions, [
        {"_id": "tx1", "Date": datetime(YEAR, 2, 1), "Type": "Income",
         "Category": "Salary", "Group": "Income", "Amount": 100000.0},
        {"_id": "tx2", "Date": datetime(YEAR, 3, 1), "Type": "Income",
         "Category": "Freelance", "Group": "Income", "Amount": 20000.0},
        {"_id": "tx3", "Date": datetime(YEAR, 4, 1), "Type": "Expense",
         "Category": "Charity", "Group": "Giving", "Amount": -5000.0},
    ])
    tax.sync_mapping()
    tax.set_mapping({"category": "Charity", "role": "DEDUCTIBLE", "schedule": "A"})
    tax.set_mapping({"category": "Freelance", "deduction_type": "1099-NEC"})
    tax.set_config({"filing_status": "SINGLE", "state_rate": 5.64, "fed_withholding": 15000,
                          "contrib_401k": 10000, "freelance": True, "use_itemized": "AUTO"})


def test_mapping_seeds_income_role(store_client):
    _seed()
    roles = {m["category"]: m["role"] for m in tax.list_mapping()}
    assert roles["Salary"] == "INCOME"          # Type==Income
    assert roles["Charity"] == "DEDUCTIBLE"      # set by hand


def test_full_tax_calc(store_client):
    _seed()
    c = tax.calc_full_tax(YEAR)
    assert c["gross_income"] == 120000.0
    assert c["above_the_line"] == 10000.0        # 401k
    assert c["agi"] == 110000.0
    assert c["deduction_used"] == 15000.0        # std (15000) > itemized (5000)
    assert c["taxable_income"] == 95000.0
    assert c["federal_tax"] == 15814.0
    assert c["se_tax"] == 1530.0                 # 20000 * 0.5 * 0.153
    assert c["state_tax"] == 5358.0              # 5.64% of 95000
    assert c["total_liability"] == 22702.0
    assert c["total_payments"] == 15000.0
    assert c["refund_owe"] == -7702.0            # owe
    assert c["marginal_rate"] == 0.22


def test_itemized_toggle(store_client):
    _seed()
    tax.set_config({"use_itemized": "YES"})
    c = tax.calc_full_tax(YEAR)
    assert c["deduction_used"] == 5000.0         # forced itemized
    assert c["taxable_income"] == 105000.0       # 110000 - 5000


def test_config_validation(store_client):
    with pytest.raises(DomainError):
        tax.set_config({"filing_status": "BOGUS"})
    with pytest.raises(DomainError):
        tax.set_config({"fed_withholding": "abc"})


def test_quarterly_safe_harbor_from_history(store_client):
    _seed()
    tax.add_history({"tax_year": YEAR - 1, "agi": 100000,
                           "total_liability": 10000, "federal_tax": 9000})
    q = tax.quarterly_estimates(YEAR)
    assert q["prior_liability"] == 10000.0
    assert q["safe_harbor_rate"] == 1.0          # prior AGI < 150k
    assert q["recommended_per_q"] == 2500.0      # min(2500 safe-harbor, 5107 of 90%-current)
    assert len(q["quarters"]) == 4


def test_tax_page_and_api_render(store_client):
    _seed()
    r = store_client.get("/tax?year=" + str(YEAR))
    assert r.status_code == 200
    assert "Tax calculation" in r.text and "Quarterly estimates" in r.text
    body = (store_client.get("/api/tax/calc?year=" + str(YEAR))).json()
    assert body["calc"]["gross_income"] == 120000.0 and "quarterly" in body
