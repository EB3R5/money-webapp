"""Tax — income, deductions, liability, and quarterly estimates over the stores (engine logic
carried over from the household's earlier spreadsheet tooling).

Where each piece of data lives:

* SHARED — derived live from `transactions`, never re-stored,
  routed by a category→tax-role mapping:
    - Income     : categories tagged INCOME (gross income, by income type).
    - Deductions : categories tagged DEDUCTIBLE (|amount|, with Schedule A/C + type).
* TAX-SPECIFIC manual data, stored here:
    - taxConfig (`metrics_config`/id="tax") : filing status, state rate, withholding, estimated
      payments, 401k/HSA/IRA/student-loan, itemized + freelance toggles, tax year.
    - `tax_category_mapping` : category → tax_role / deduction_type / schedule / notes.
    - `tax_history`          : manual YoY log (prior-year AGI + liability feed the safe harbor).
* STATIC constants below : 2025 federal brackets, standard deductions, SE tax,
  quarterly deadlines.
* COMPUTED live : calc_full_tax() and quarterly_estimates().
"""

from datetime import UTC, datetime

from . import registry, rollup
from .category_mapping import CategoryMapping
from .store.tax_category_mapping import tax_category_mapping
from .store.tax_history import tax_history
from .values import parse_amount
from .web import DomainError

TAX_ROLES = ("INCOME", "DEDUCTIBLE", "IGNORE")
FILING_STATUSES = ("SINGLE", "MFJ", "HOH")

# 2025 federal brackets. HOH falls back to SINGLE (no separate HOH table is kept).
BRACKETS = {
    "SINGLE": [(0, 11925, 0.10), (11925, 48475, 0.12), (48475, 103350, 0.22),
               (103350, 197300, 0.24), (197300, 250525, 0.32), (250525, 626350, 0.35),
               (626350, float("inf"), 0.37)],
    "MFJ": [(0, 23850, 0.10), (23850, 96950, 0.12), (96950, 206700, 0.22),
            (206700, 394600, 0.24), (394600, 501050, 0.32), (501050, 751600, 0.35),
            (751600, float("inf"), 0.37)],
}
# State income tax is one effective rate the person enters (their state tax ÷ taxable income
# from last year's return), applied to taxable income. States differ in base, deductions and
# credits far more than in brackets, so a table of brackets would be wrong in more places
# than this is; one number the person owns is honest about being an estimate.
STANDARD_DEDUCTION = {"SINGLE": 15000, "MFJ": 30000, "HOH": 22500}
SE_TAX_RATE = 0.153
SE_DEDUCTIBLE_PORTION = 0.5

QUARTERLY_DEADLINES = [
    {"quarter": "Q1", "due": "2025-04-15", "label": "Jan 1 – Mar 31"},
    {"quarter": "Q2", "due": "2025-06-16", "label": "Apr 1 – May 31"},
    {"quarter": "Q3", "due": "2025-09-15", "label": "Jun 1 – Aug 31"},
    {"quarter": "Q4", "due": "2026-01-15", "label": "Sep 1 – Dec 31"},
]

DEFAULT_CONFIG = {
    "tax_year": datetime.now(UTC).year,
    "filing_status": "SINGLE",
    "state_rate": 0.0,          # a fraction; the form takes a percent
    "fed_withholding": 0.0,
    "state_withholding": 0.0,
    "estimated_payments": 0.0,
    "contrib_401k": 0.0,
    "hsa": 0.0,
    "ira": 0.0,
    "student_loan_int": 0.0,
    "use_itemized": "AUTO",   # AUTO | YES | NO
    "freelance": False,
}
_NUMERIC = ("fed_withholding", "state_withholding", "estimated_payments", "contrib_401k",
            "hsa", "ira", "student_loan_int")
CONFIG = registry.ConfigDoc("tax", DEFAULT_CONFIG)


def _bracket_tax(income, brackets):
    """Progressive tax over (min, max, rate) bands."""
    tax = 0.0
    for lo, hi, rate in brackets:
        if income <= lo:
            break
        tax += (min(income, hi) - lo) * rate
    return tax


def _marginal_rate(income, brackets):
    rate = 0.0
    for lo, _hi, r in brackets:
        if income > lo:
            rate = r
    return rate


# --- config -----------------------------------------------------------------

def get_config() -> dict:
    return CONFIG.get()


def set_config(body: dict) -> dict:
    cfg = CONFIG.get()
    if "tax_year" in body:
        cfg["tax_year"] = int(parse_amount(body["tax_year"], "tax_year", blank=0.0))
    if "filing_status" in body:
        fs = (body["filing_status"] or "").strip().upper()
        if fs not in FILING_STATUSES:
            raise DomainError(f"filing_status must be one of {', '.join(FILING_STATUSES)}")
        cfg["filing_status"] = fs
    if "state_rate" in body:
        pct = parse_amount(body["state_rate"], "state_rate", blank=0.0)
        if not 0 <= pct <= 100:
            raise DomainError("state_rate is a percent between 0 and 100")
        cfg["state_rate"] = round(pct / 100, 6)
    if "use_itemized" in body:
        ui = (body["use_itemized"] or "").strip().upper()
        if ui not in ("AUTO", "YES", "NO"):
            raise DomainError("use_itemized must be AUTO, YES, or NO")
        cfg["use_itemized"] = ui
    if "freelance" in body:
        cfg["freelance"] = bool(body["freelance"]) and str(body["freelance"]).lower() not in ("false", "no", "0")
    for k in _NUMERIC:
        if k in body:
            cfg[k] = parse_amount(body[k], k, blank=0.0)
    return CONFIG.save(cfg)


# --- category mapping -------------------------------------------------------

# The tax adapter onto the shared Category mapping module (CONTEXT.md: Category mapping).
# Only the bespoke dict reduction (_mapping_dict, with deduction fields) stays below.

def _seed_role(category, group, is_income: bool) -> str:
    return "INCOME" if is_income else "IGNORE"


_mapping = CategoryMapping(
    store=tax_category_mapping, role_field="tax_role", roles=TAX_ROLES, seed=_seed_role,
    new_extra={"deduction_type": None, "schedule": None, "notes": "auto-synced — review role"})


def sync_mapping() -> dict:
    return _mapping.sync()


def list_mapping() -> list:
    return [{"category": d["_id"], "group": d.get("Group"),
             "role": d.get("tax_role") or "IGNORE", "deduction_type": d.get("deduction_type"),
             "schedule": d.get("schedule"), "notes": d.get("notes")}
            for d in _mapping.docs()]


def set_mapping(body: dict) -> dict:
    return _mapping.set_role(
        body, extra_fields=("deduction_type", "schedule", "notes"), role_required=False)


def _mapping_dict() -> dict:
    return {d["_id"]: {"role": d.get("tax_role") or "IGNORE",
                       "deduction_type": d.get("deduction_type"),
                       "schedule": d.get("schedule"), "group": d.get("Group")}
            for d in tax_category_mapping.list()}


# --- income / deductions (derived from transactions) ------------------------

def _is_freelance(deduction_type) -> bool:
    s = (deduction_type or "").lower()
    return "1099" in s or "self" in s or "freelance" in s


def income_deductions(year: int, mapping: dict | None = None) -> dict:
    """Per-category income & deduction rollups for the tax year, routed by the mapping."""
    mapping = mapping if mapping is not None else _mapping_dict()
    income, deductions = [], []
    for r in rollup.by_category(year=year):
        rule = mapping.get(r["category"])
        if not rule:
            continue
        if rule["role"] == "INCOME":
            income.append({"category": r["category"], "group": r.get("group"),
                           "income_type": rule.get("deduction_type") or "Income",
                           "amount": round(r["amount"], 2)})
        elif rule["role"] == "DEDUCTIBLE":
            deductions.append({"category": r["category"], "group": r.get("group"),
                               "deduction_type": rule.get("deduction_type"),
                               "schedule": rule.get("schedule"),
                               "amount": round(r["absamt"], 2)})
    income.sort(key=lambda x: -x["amount"])
    deductions.sort(key=lambda x: -x["amount"])
    return {"income": income, "deductions": deductions}


# --- tax calculation --------------------------------------------------------

def calc_full_tax(year: int, cfg: dict | None = None) -> dict:
    """Full federal + SE + state calc for the year (TaxEngine.calcFullTax_)."""
    cfg = cfg or get_config()
    rows = income_deductions(year)
    filing = cfg["filing_status"]

    gross_income = round(sum(r["amount"] for r in rows["income"]), 2)
    itemized_total = round(sum(r["amount"] for r in rows["deductions"]), 2)
    above_the_line = round(cfg["contrib_401k"] + cfg["hsa"] + cfg["student_loan_int"] + cfg["ira"], 2)
    std_deduction = STANDARD_DEDUCTION.get(filing, STANDARD_DEDUCTION["SINGLE"])

    if cfg["use_itemized"] == "YES":
        deduction_used = itemized_total
    elif cfg["use_itemized"] == "NO":
        deduction_used = std_deduction
    else:
        deduction_used = max(std_deduction, itemized_total)

    agi = round(gross_income - above_the_line, 2)
    taxable = max(0.0, round(agi - deduction_used, 2))

    fed_brackets = BRACKETS.get(filing, BRACKETS["SINGLE"])
    federal_tax = round(_bracket_tax(taxable, fed_brackets), 2)

    se_tax = 0.0
    if cfg["freelance"]:
        freelance_income = sum(r["amount"] for r in rows["income"] if _is_freelance(r["income_type"]))
        se_tax = round(freelance_income * (1 - SE_DEDUCTIBLE_PORTION) * SE_TAX_RATE, 2)

    state_rate = cfg.get("state_rate") or 0.0
    state_tax = round(taxable * state_rate, 2)

    total_liability = round(federal_tax + se_tax + state_tax, 2)
    total_payments = round(cfg["fed_withholding"] + cfg["state_withholding"] + cfg["estimated_payments"], 2)

    return {
        "year": year, "filing_status": filing, "state_rate": state_rate,
        "gross_income": gross_income, "above_the_line": above_the_line, "agi": agi,
        "std_deduction": std_deduction, "itemized_total": itemized_total,
        "deduction_used": deduction_used, "taxable_income": taxable,
        "federal_tax": federal_tax, "se_tax": se_tax, "state_tax": state_tax,
        "total_liability": total_liability, "total_payments": total_payments,
        "refund_owe": round(total_payments - total_liability, 2),
        "effective_rate": round(federal_tax / gross_income, 4) if gross_income > 0 else 0.0,
        "marginal_rate": _marginal_rate(taxable, fed_brackets),
    }


# --- tax history (CRUD) -----------------------------------------------------

def list_history() -> list:
    return [{k: d.get(k) for k in (
        "tax_year", "filing_status", "gross_income", "agi", "taxable_income",
        "federal_tax", "state_tax", "total_liability", "withholding_payments",
        "refund_owe", "effective_rate", "notes")} | {"id": str(d["_id"])}
        for d in tax_history.list(order=[("tax_year", "desc")])]


def add_history(body: dict) -> dict:
    year = int(parse_amount(body.get("tax_year"), "tax_year", blank=0.0))
    if not year:
        raise DomainError("tax_year is required")
    fields = {"tax_year": year,
              "filing_status": (body.get("filing_status") or "").strip().upper() or None,
              "notes": (body.get("notes") or "").strip() or None}
    for f in ("gross_income", "agi", "taxable_income", "federal_tax", "state_tax",
              "total_liability", "withholding_payments", "refund_owe"):
        fields[f] = parse_amount(body.get(f), f, blank=0.0)
    fields["effective_rate"] = (round(fields["federal_tax"] / fields["gross_income"], 4)
                                if fields["gross_income"] > 0 else 0.0)
    return registry.add_doc(tax_history, fields)


def delete_history(body: dict) -> dict:
    return registry.delete_doc(tax_history, body.get("id"), "history row")


# --- quarterly estimates ----------------------------------------------------

def quarterly_estimates(year: int, cfg: dict | None = None) -> dict:
    """Safe-harbor quarterly plan (QuarterlyEngine): recommended/Q = min(prior-year safe
    harbor, 90% of current). Prior-year liability/AGI come from taxHistory."""
    cfg = cfg or get_config()
    calc = calc_full_tax(year, cfg)
    current_liability = calc["total_liability"]
    total_payments = calc["total_payments"]

    prior = tax_history.one({"tax_year": year - 1})
    prior_liability = (prior or {}).get("total_liability", 0.0) or 0.0
    prior_agi = (prior or {}).get("agi", 0.0) or 0.0

    safe_harbor_rate = 1.10 if prior_agi > 150000 else 1.00
    safe_harbor_per_q = round(prior_liability * safe_harbor_rate / 4, 2)
    ninety_per_q = round(current_liability * 0.90 / 4, 2)
    recommended_per_q = min(safe_harbor_per_q, ninety_per_q) if prior_liability else ninety_per_q

    quarters = []
    for i, q in enumerate(QUARTERLY_DEADLINES):
        needed = round(recommended_per_q * (i + 1), 2)
        amount_due = max(0.0, round(needed - total_payments, 2))
        quarters.append({
            "quarter": q["quarter"], "period": q["label"], "due": q["due"],
            "needed_ytd": needed, "payments_ytd": total_payments,
            "amount_due": amount_due, "safe_harbor_per_q": safe_harbor_per_q,
            "status": "✅ On Track" if total_payments >= needed else "⚠️ Payment Due",
        })
    return {
        "year": year, "prior_year": year - 1, "prior_liability": round(prior_liability, 2),
        "prior_agi": round(prior_agi, 2), "safe_harbor_rate": safe_harbor_rate,
        "recommended_per_q": recommended_per_q, "current_liability": current_liability,
        "quarters": quarters,
    }
