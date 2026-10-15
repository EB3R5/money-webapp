"""Savings — savings rate, goals, and projections over the stores.
Served on the Metrics page (`/metrics`); the data-freshness snapshot lives in data_health.py
and the ratio scores in financial_health.py — three distinct concepts, no shared name.

The model (carried over from the household's earlier spreadsheet tooling):

* **Category Mapping** (`savings_category_mapping`): every category carries a Savings_Role —
  SAVINGS / INCOME / IGNORE. This mapping is the single source of truth for what counts.
  syncCategoryMapping seeds it from the ledger: INCOME for categories whose transactions are
  Type=="Income", SAVINGS for the obvious "Investing Deposit", everything else IGNORE — then
  you adjust roles by hand.
* **Savings Rate** (per configured **year**): for each
  month, income = Σ(Amount) over INCOME-role categories (or the income override if set),
  actual savings = Σ(|Amount|) over SAVINGS-role categories — "money moved into savings"; it
  does NOT net withdrawals back out. Then target = income × target_rate,
  gap = actual − target, and running totals carry across the year.
* **Goals** (`savings_goals`): named goals; current balance = the pooled total saved for the
  year (single-account model), with remaining, % complete, months to
  target, required monthly, projected completion, and on-track status.

Config (`metrics_config`/id="savings"): target_rate (default 0.20) and income_override (0 = off).
"""

from datetime import UTC, date, datetime, timedelta

from . import registry, rollup
from .category_mapping import CategoryMapping
from .store.savings_category_mapping import savings_category_mapping
from .store.accounts import accounts
from .store.savings_goals import savings_goals
from .values import parse_amount, parse_date
from .web import DomainError

ROLES = ("SAVINGS", "INCOME", "IGNORE")
# Categories auto-tagged SAVINGS on first seed (everything else non-Income → IGNORE): the user
# marks SAVINGS by hand; this is only a sensible starting point. "Savings" is the
# Albert auto-save app (recorded as outflows) — valid contributions, summed as |amount|.
DEFAULT_SAVINGS_CATEGORIES = {"Investing Deposit", "Investment", "Savings"}

DEFAULT_SAVINGS_CONFIG = {
    "target_rate": 0.20,     # aspirational savings rate (fraction of income)
    "income_override": 0.0,  # >0 replaces computed monthly income (paychecks not in the ledger)
    # The 5 "what if I saved X%" rates for the Rate Scenarios projection.
    "scenario_rates": [0.10, 0.15, 0.20, 0.25, 0.30],
}

PROJECTION_MONTHS = 24   # forward window for goal projections (ProjectionEngine)
SCENARIO_MONTHS = 36     # forward window for rate scenarios (ScenarioEngine)

CONFIG = registry.ConfigDoc("savings", DEFAULT_SAVINGS_CONFIG)


def _norm_rate(v) -> float:
    """A percent (20) or fraction (0.2) → fraction in [0, 1]."""
    try:
        r = float(v)
    except (TypeError, ValueError):
        raise DomainError("rate must be a number")
    if r > 1:
        r = r / 100
    if not 0 <= r <= 1:
        raise DomainError("rate must be between 0 and 1 (or 0–100%)")
    return round(r, 4)


def _add_months(label: str, n: int) -> str:
    """'YYYY-MM' + n months → 'YYYY-MM'."""
    y, m = (int(x) for x in label.split("-"))
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12}-{idx % 12 + 1:02d}"


# --- config -----------------------------------------------------------------

def get_savings_config() -> dict:
    return CONFIG.get()


def set_savings_config(body: dict) -> dict:
    """Patch the savings config. target_rate accepts a fraction (0.2) or percent (20);
    income_override is a dollar amount (0 disables). Only provided keys change."""
    cfg = CONFIG.get()
    if "target_rate" in body:
        cfg["target_rate"] = _norm_rate(body["target_rate"])
    if "scenario_rates" in body:
        v = body["scenario_rates"]
        if not isinstance(v, list) or not v:
            raise DomainError("scenario_rates must be a non-empty list")
        cfg["scenario_rates"] = [_norm_rate(x) for x in v]
    if "income_override" in body:
        try:
            ov = float(body["income_override"] or 0)
        except (TypeError, ValueError):
            raise DomainError("income_override must be a number")
        if ov < 0:
            raise DomainError("income_override cannot be negative")
        cfg["income_override"] = round(ov, 2)
    return CONFIG.save(cfg)


# --- category mapping (Savings_Role per category) ---------------------------
# The savings adapter onto the shared Category mapping module (CONTEXT.md: Category mapping).
# Only the bespoke role-set reduction (_role_categories) stays here; roster + sync + the role
# upsert live in CategoryMapping.

def _seed_role(category: str, group, is_income: bool) -> str:
    # The default-savings guess wins even for income-typed categories (e.g. "Investing
    # Deposit" carries Type=="Income" rows but is really a contribution), so there's a
    # sensible non-zero starting point; the user retags from there.
    if category in DEFAULT_SAVINGS_CATEGORIES:
        return "SAVINGS"
    if is_income:
        return "INCOME"
    return "IGNORE"


_mapping = CategoryMapping(
    store=savings_category_mapping, role_field="Savings_Role", roles=ROLES,
    seed=_seed_role, new_extra={"Notes": "auto-synced — review role"})


def sync_mapping() -> dict:
    return _mapping.sync()


def list_mapping() -> list:
    return [{"category": d["_id"], "group": d.get("Group"),
             "role": d.get("Savings_Role") or "IGNORE", "notes": d.get("Notes")}
            for d in _mapping.docs()]


def set_mapping_role(body: dict) -> dict:
    return _mapping.set_role(body)


def _role_categories() -> tuple[list, list]:
    """(income_categories, savings_categories) from the mapping."""
    income, savings = [], []
    for d in savings_category_mapping.list({"Savings_Role": ["INCOME", "SAVINGS"]}):
        (income if d["Savings_Role"] == "INCOME" else savings).append(d["_id"])
    return income, savings


# --- savings rate (per year) ------------------------------------------------

def _savings_summary(rows: list, target_rate: float) -> dict:
    n = len(rows)
    total_saved = round(sum(r["savings"] for r in rows), 2)
    total_income = round(sum(r["income"] for r in rows), 2)
    return {
        "months": n,
        "total_saved": total_saved,
        "total_income": total_income,
        "avg_monthly": round(total_saved / n, 2) if n else 0.0,
        "overall_rate": round(total_saved / total_income, 4) if total_income > 0 else 0.0,
        "target_rate": target_rate,
    }


def savings_rate_by_month(year: int, cfg: dict | None = None) -> dict:
    """Month-by-month income, actual savings (Σ|Amount| over SAVINGS cats), target, gap, rate,
    and running totals for one year — driven by the Category Mapping roles. Mirrors
    SavingsRateEngine.recalculateSavingsRate."""
    cfg = cfg or get_savings_config()
    income_cats, savings_cats = _role_categories()
    target_rate = cfg["target_rate"]
    override = cfg["income_override"]

    rows = []
    run_saved = run_target = 0.0
    for r in rollup.monthly_role_sums(income_cats, savings_cats, year=year):
        income = round(override if override > 0 else r["income"], 2)
        savings = round(r["savings"], 2)
        target = round(income * target_rate, 2)
        run_saved += savings
        run_target += target
        rows.append({
            "month": r["month"],
            "income": income,
            "savings": savings,
            "target": target,
            "gap": round(savings - target, 2),
            "rate": round(savings / income, 4) if income > 0 else 0.0,
            "running_saved": round(run_saved, 2),
            "running_target": round(run_target, 2),
            "running_gap": round(run_saved - run_target, 2),
        })

    return {"rows": rows, "summary": _savings_summary(rows, target_rate),
            "target_rate": target_rate, "year": year}


# --- history, projections, scenarios ----------------------------------------

def savings_history(cfg: dict | None = None) -> list:
    """All-time monthly series [{month, savings, income, balance}] — the actual cumulative
    savings balance over every month present in the ledger. The historical curve the
    projection and scenario charts continue forward from."""
    cfg = cfg or get_savings_config()
    income_cats, savings_cats = _role_categories()
    rows, balance = [], 0.0
    for r in rollup.monthly_role_sums(income_cats, savings_cats):
        balance += r["savings"]
        rows.append({
            "month": r["month"],
            "savings": round(r["savings"], 2),
            "income": round(r["income"], 2),
            "balance": round(balance, 2),
        })
    return rows


def projections(year: int, cfg: dict | None = None) -> dict:
    """Goal projections: the historical balance curve plus a PROJECTION_MONTHS forward curve
    at the selected year's average monthly savings, with each goal's target for reference.
    Mirrors ProjectionEngine (projected = total_saved + avg_monthly × m)."""
    cfg = cfg or get_savings_config()
    history = savings_history(cfg)
    avg_monthly = (savings_rate_by_month(year, cfg))["summary"]["avg_monthly"]
    balance_now = history[-1]["balance"] if history else 0.0
    last = history[-1]["month"] if history else f"{year}-12"

    forward, bal = [], balance_now
    for m in range(1, PROJECTION_MONTHS + 1):
        bal += avg_monthly
        forward.append({"month": _add_months(last, m), "projected": round(bal, 2)})

    return {
        "history": history,
        "forward": forward,
        "avg_monthly": avg_monthly,
        "balance_now": balance_now,
        "goals": list_goals(year, cfg),
    }


def rate_scenarios(year: int, cfg: dict | None = None) -> dict:
    """Rate scenarios: the historical balance curve plus a SCENARIO_MONTHS forward curve per
    configured rate (balance = balance_now + avg_income × rate × m). Mirrors ScenarioEngine."""
    cfg = cfg or get_savings_config()
    history = savings_history(cfg)
    summary = (savings_rate_by_month(year, cfg))["summary"]
    avg_income = (cfg["income_override"] if cfg["income_override"] > 0
                  else (summary["total_income"] / summary["months"] if summary["months"] else 0.0))
    balance_now = history[-1]["balance"] if history else 0.0
    last = history[-1]["month"] if history else f"{year}-12"

    months = [_add_months(last, m) for m in range(1, SCENARIO_MONTHS + 1)]
    scenarios = []
    for rate in cfg["scenario_rates"]:
        scenarios.append({
            "rate": rate,
            "label": f"{rate * 100:.0f}%",
            "balances": [round(balance_now + avg_income * rate * m, 2)
                         for m in range(1, SCENARIO_MONTHS + 1)],
        })
    return {
        "history": history,
        "forward_months": months,
        "scenarios": scenarios,
        "avg_income": round(avg_income, 2),
        "balance_now": balance_now,
    }


# --- goals ------------------------------------------------------------------

def _as_dt(v) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").replace(tzinfo=UTC)


def _iso(v):
    """Store dates come back as date objects; the page and the API speak ISO strings."""
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _goal_balance(g: dict, total_saved: float, account_balances: dict | None) -> tuple[float, str]:
    """(current balance, source): a typed balance wins, then the linked account's current
    amount, then the pooled total saved (the original single-savings-account model)."""
    if g.get("balance_override") not in (None, ""):
        return float(g["balance_override"]), "typed"
    acct = (g.get("balance_account") or "").strip()
    if acct and account_balances and acct in account_balances:
        return float(account_balances[acct] or 0), "account"
    return float(total_saved), "pooled"


def _derive_goal(g: dict, total_saved: float, avg_monthly: float,
                 today: datetime | None = None, account_balances: dict | None = None) -> dict:
    """Fill a goal's computed columns. Current balance is the goal's own when it has one —
    a typed balance or a linked account (ADR-0023 follow-up #182) — else the pooled total
    saved (single savings-account model, mirroring GoalsEngine.refreshGoals)."""
    today = today or datetime.now(UTC)
    target = float(g.get("target_amount") or 0)
    current, balance_source = _goal_balance(g, total_saved, account_balances)
    remaining = max(0.0, round(target - current, 2))
    pct = round(min(1.0, current / target), 4) if target > 0 else 0.0

    months_to_target = None
    if g.get("target_date"):
        months_to_target = max(0.0, (_as_dt(g["target_date"]) - today).days / 30.44)
    required_monthly = (round(remaining / months_to_target, 2)
                        if months_to_target and months_to_target > 0 else None)

    if remaining <= 0:
        projected, on_track = "Achieved", "achieved"
    elif avg_monthly > 0:
        projected = (today + timedelta(days=(remaining / avg_monthly) * 30.44)).strftime("%Y-%m-%d")
        on_track = "no_date" if required_monthly is None else (
            "on_track" if avg_monthly >= required_monthly else "behind")
    else:
        projected, on_track = None, "no_savings"

    return {
        "id": str(g["_id"]),
        "name": g.get("name"),
        "target_amount": round(target, 2),
        "target_date": _iso(g.get("target_date")),
        "current_balance": round(current, 2),
        "remaining": remaining,
        "pct": pct,
        "months_remaining": round(months_to_target, 1) if months_to_target is not None else None,
        "required_monthly": required_monthly,
        "projected_completion": projected,
        "on_track": on_track,
        "notes": g.get("notes"),
        "monthly_contribution": round(float(g.get("monthly_contribution") or 0), 2),   # ADR-0023 D4
        "balance_source": balance_source,
        "balance_account": (g.get("balance_account") or None),
        "balance_override": (round(float(g["balance_override"]), 2)
                             if g.get("balance_override") not in (None, "") else None),
    }


def account_balances() -> dict:
    """{Account name: current Amount} for every account — the balance a goal may link to."""
    return {a["Account"]: a.get("Amount") for a in accounts.list() if a.get("Account")}


def list_goals(year: int, cfg: dict | None = None) -> list:
    """Goals with progress: each against its own balance when it has one, else the selected
    year's pooled total; the average saved per month projects completion either way."""
    summary = (savings_rate_by_month(year, cfg))["summary"]
    avg, total = summary["avg_monthly"], summary["total_saved"]
    balances = account_balances()
    return [_derive_goal(g, total, avg, account_balances=balances)
            for g in savings_goals.list(order=[("_created_at", "asc")])]


def add_goal(body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise DomainError("name is required")
    target = parse_amount(body.get("target_amount"), "target_amount")
    if target <= 0:
        raise DomainError("target_amount must be positive")
    return registry.add_doc(savings_goals, {
        "name": name,
        "target_amount": target,
        "target_date": parse_date(body.get("target_date"), "target_date"),
        "notes": (body.get("notes") or "").strip() or None,
        **(_goal_extras(body)),
    })


def _goal_extras(body: dict) -> dict:
    """The per-goal fields ADR-0023 added, validated: a monthly contribution (≥ 0), a
    linked account by name (must exist), a typed balance (≥ 0, blank clears)."""
    out = {}
    if "monthly_contribution" in body:
        per = parse_amount(body["monthly_contribution"], "monthly_contribution", blank=0.0)
        if per < 0:
            raise DomainError("monthly_contribution cannot be negative")
        out["monthly_contribution"] = per
    if "balance_account" in body:
        name = (body["balance_account"] or "").strip()
        if name and name not in account_balances():
            raise DomainError(f"unknown account '{name}'")
        out["balance_account"] = name or None
    if "balance_override" in body:
        v = parse_amount(body["balance_override"], "balance_override", blank=None)
        if v is not None and v < 0:
            raise DomainError("balance_override cannot be negative")
        out["balance_override"] = v
    return out


def update_goal(body: dict) -> dict:
    updates = {}
    if "name" in body:
        name = (body["name"] or "").strip()
        if not name:
            raise DomainError("name cannot be blank")
        updates["name"] = name
    if "target_amount" in body:
        target = parse_amount(body["target_amount"], "target_amount")
        if target <= 0:
            raise DomainError("target_amount must be positive")
        updates["target_amount"] = target
    if "target_date" in body:
        updates["target_date"] = parse_date(body["target_date"], "target_date")
    if "notes" in body:
        updates["notes"] = (body["notes"] or "").strip() or None
    updates.update(_goal_extras(body))             # these live in the goal's spill JSON
    return registry.update_doc(savings_goals, body.get("id"), updates, "goal")


def delete_goal(body: dict) -> dict:
    return registry.delete_doc(savings_goals, body.get("id"), "goal")
