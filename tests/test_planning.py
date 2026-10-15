"""Planning facts (app/planning.py, ADR-0021): the budget pick rule (D4), month_facts()
on the budget-report seed, the net savings rate (D3), and the trailing series."""

from datetime import UTC, datetime

from app import planning
from app.store.balance_history import balance_history
from app.store.budget_lines import budget_lines
from app.store.budgets import budgets
from app.store.categories import categories
from app.store.transactions import transactions
from tests import dbhelper


def seed_month():
    """January 2026: Salary 8000 in, Food 1455 + Dining 210 out (Dining unbudgeted), Rent
    budgeted with no spend, a zero Gifts line, a blank-Group row; February has one row."""
    dbhelper.seed(categories, [
        {"_id": "Salary", "Category": "Salary", "Group": "Salary", "Type": "Income"},
        {"_id": "Rent", "Category": "Rent", "Group": "Rent", "Type": "Expense"},
        {"_id": "Groceries", "Category": "Groceries", "Group": "Food", "Type": "Expense"},
        {"_id": "Dining", "Category": "Dining", "Group": "Dining", "Type": "Expense"},
    ])
    dbhelper.seed(transactions, [
        {"_id": "x1", "Date": datetime(2026, 1, 15), "Group": "Food", "Category": "Groceries", "Amount": -1455.0, "Type": "Expense"},
        {"_id": "x2", "Date": datetime(2026, 1, 20), "Group": "Dining", "Category": "Dining", "Amount": -210.0, "Type": "Expense"},
        {"_id": "x3", "Date": datetime(2026, 1, 1), "Group": "Salary", "Category": "Salary", "Amount": 8000.0, "Type": "Income"},
        {"_id": "x4", "Date": datetime(2026, 2, 15), "Group": "Dining", "Category": "Dining", "Amount": -900.0, "Type": "Expense"},
        {"_id": "x5", "Date": datetime(2026, 1, 9), "Group": "", "Category": "", "Amount": -33.0, "Type": "Expense"},
    ])
    dbhelper.seed(budgets, [
        {"_id": "bud_a", "budgetId": "BUD001", "versionName": "Baseline", "month": "2026-01",
         "status": "saved", "_created_at": datetime(2026, 1, 1, tzinfo=UTC)}])
    dbhelper.seed(budget_lines, [
        {"budget": "bud_a", "position": 0, "group": "Food", "amount": -1200},
        {"budget": "bud_a", "position": 1, "group": "Rent", "amount": -2100},
        {"budget": "bud_a", "position": 2, "group": "Gifts", "amount": 0},
    ])


def test_month_helpers():
    assert planning.is_month("2026-09") and not planning.is_month("2026-13")
    assert not planning.is_month("2026-9") and not planning.is_month("garbage") and not planning.is_month("")
    assert planning.month_label("2026-09") == "September 2026"
    assert planning.next_month("2026-12") == "2027-01" and planning.prev_month("2027-01") == "2026-12"
    assert planning.days_in("2026-02") == 28


def test_budget_for_month_prefers_saved_then_newest_draft(store_db):
    seed_month()
    dbhelper.seed(budgets, [
        {"_id": "bud_b", "budgetId": "BUD002", "versionName": "Newer draft", "month": "2026-01",
         "status": "draft", "_created_at": datetime(2026, 1, 20, tzinfo=UTC)},
        {"_id": "bud_c", "budgetId": "BUD003", "versionName": "Feb draft", "month": "2026-02",
         "status": "draft", "_created_at": datetime(2026, 2, 1, tzinfo=UTC)},
        {"_id": "bud_d", "budgetId": "BUD004", "versionName": "Feb older", "month": "2026-02",
         "status": "draft", "_created_at": datetime(2026, 1, 25, tzinfo=UTC)},
    ])
    assert (planning.budget_for_month("2026-01"))["_id"] == "bud_a"      # saved beats a newer draft
    assert (planning.budget_for_month("2026-02"))["_id"] == "bud_c"      # newest draft
    assert planning.budget_for_month("2026-03") is None


def test_budget_report_rows_pills_and_spend_totals(store_db):
    seed_month()
    rep = planning.budget_report("2026-01")
    by = {r["group"]: r for r in rep["rows"]}
    assert rep["versionName"] == "Baseline" and rep["status"] == "saved"
    assert by["Food"]["budget_abs"] == 1200.0 and by["Food"]["actual_abs"] == 1455.0
    assert by["Food"]["over"] == 255.0 and by["Food"]["pill"] == {"text": "high over", "cls": "over"}   # 21% over
    assert by["Rent"]["pill"] == {"text": "no activity", "cls": "none"}
    assert by["Dining"]["pill"] == {"text": "unbudgeted", "cls": "warn"}
    assert by["Gifts"]["pill"] == {"text": "no activity", "cls": "none"}       # zero line, no spend
    assert by["Salary"]["kind"] == "income"
    # Spend totals are expense-side only: Salary's 8000 is not in them.
    assert rep["spend_budget"] == 3300.0 and rep["spend_actual"] == 1665.0
    assert rep["on_target"] == 0
    assert planning.budget_report("2026-03") is None


def test_month_facts_rate_series_and_net_worth(store_db):
    seed_month()
    dbhelper.seed(balance_history, [
        {"_id": "s1", "Date": datetime(2025, 12, 31), "Account": "Checking", "Class": "Asset", "Balance": 1000.0},
        {"_id": "s2", "Date": datetime(2026, 1, 31), "Account": "Checking", "Class": "Asset", "Balance": 1500.0},
    ])
    f = planning.month_facts("2026-01", today=datetime(2026, 1, 10, tzinfo=UTC))
    assert f["label"] == "January 2026" and f["days"] == 31 and f["is_current"] is True
    assert f["prev"] == "2025-12" and f["next"] == "2026-02"
    assert f["income"] == 8000.0 and f["expense"] == 1698.0                # 1455 + 210 + 33 (blank Group still counts)
    assert f["net"] == 6302.0
    assert f["savings_rate"] == round(6302 / 8000, 4)                      # net ÷ income (D3)
    assert f["target_rate"] == 0.2
    assert f["months12"][-1] == "2026-01" and f["months12"][0] == "2025-02" and len(f["net12"]) == 12
    assert f["net12"][-1] == 6302.0 and f["net12"][-2] == 0.0             # zero-filled
    assert f["avg_net_12"] == 6302.0                                       # only months with rows
    assert f["avg_income_12"] == 8000.0 and f["avg_expense_12"] == 1698.0
    assert f["net_worth"]["value"] == 1500.0 and f["net_worth"]["delta"] == 500.0
    assert f["budget"]["id"] == "bud_a"
    assert f["uncategorized"] == 1                                         # x5 has a blank Category


def test_month_facts_without_income_or_budget(store_db):
    f = planning.month_facts("2024-07", today=datetime(2026, 1, 10, tzinfo=UTC))
    assert f["income"] == 0.0 and f["savings_rate"] is None and f["budget"] is None
    assert f["net_worth"] is None and f["is_current"] is False and f["avg_net_12"] == 0.0


# --- journal entries (D1) -----------------------------------------------------------------

from app.store.deletions import deletions          # noqa: E402
from app.store.journal_entries import journal_entries  # noqa: E402
from app.web import DomainError                    # noqa: E402
import pytest                                      # noqa: E402

FIGURE_KEYS = {"period", "income", "expense", "net", "savings_rate", "net_worth", "net_worth_delta",
               "net_worth_as_of", "budget_version", "budget_total", "actual_total", "misses",
               "months12", "net12", "frozen_at"}


def test_is_period_accepts_months_and_years():
    assert planning.is_period("2026-09") and planning.is_period("2026")
    assert not planning.is_period("2026-9") and not planning.is_period("26") and not planning.is_period("")


def test_first_save_freezes_the_figures_and_later_saves_keep_them(store_db):
    seed_month()
    t0 = datetime(2026, 2, 3, 9, 12, tzinfo=UTC)
    e = planning.save_entry("2026-01", "Food ran over.", today=t0)
    assert e["period"] == "2026-01" and e["body"] == "Food ran over."
    assert set(e["figures"]) == FIGURE_KEYS
    fig = e["figures"]
    assert fig["income"] == 8000.0 and fig["expense"] == 1698.0 and fig["net"] == 6302.0
    assert fig["budget_version"] == "Baseline" and fig["budget_total"] == 3300.0 and fig["actual_total"] == 1665.0
    assert fig["misses"] == [{"group": "Food", "budget": 1200.0, "actual": 1455.0, "over": 255.0},
                             {"group": "Dining", "budget": 0.0, "actual": 210.0, "over": 210.0}]   # unbudgeted counts
    assert fig["net_worth"] is None and fig["frozen_at"] == "2026-02-03T09:12:00+00:00"
    assert len(fig["net12"]) == 12 and fig["months12"][-1] == "2026-01"
    # A later save changes the body only; the ledger moving does not move the frozen figures.
    dbhelper.seed(transactions, [{"_id": "x9", "Date": datetime(2026, 1, 28), "Group": "Food",
                                        "Category": "Groceries", "Amount": -100.0, "Type": "Expense"}])
    e2 = planning.save_entry("2026-01", "Food ran over. Again.", today=datetime(2026, 3, 1, tzinfo=UTC))
    assert e2["body"] == "Food ran over. Again." and e2["figures"]["expense"] == 1698.0
    assert e2["_id"] == e["_id"] and journal_entries.count() == 1


def test_refreeze_recomputes_the_figures(store_db):
    seed_month()
    planning.save_entry("2026-01", "x", today=datetime(2026, 2, 1, tzinfo=UTC))
    dbhelper.seed(transactions, [{"_id": "x9", "Date": datetime(2026, 1, 28), "Group": "Food",
                                        "Category": "Groceries", "Amount": -100.0, "Type": "Expense"}])
    e = planning.refreeze("2026-01", today=datetime(2026, 3, 1, 8, 0, tzinfo=UTC))
    assert e["figures"]["expense"] == 1798.0 and e["figures"]["frozen_at"] == "2026-03-01T08:00:00+00:00"
    with pytest.raises(DomainError):
        planning.refreeze("2025-06")                                 # no entry


def test_year_entry_freezes_year_figures(store_db):
    seed_month()
    e = planning.save_entry("2026", "The year.", today=datetime(2027, 1, 2, tzinfo=UTC))
    fig = e["figures"]
    assert set(fig) == FIGURE_KEYS and fig["period"] == "2026"
    assert fig["income"] == 8000.0 and fig["expense"] == 2598.0 and fig["net"] == 5402.0   # Jan + Feb
    assert fig["budget_version"] is None and fig["misses"] == []
    assert fig["months12"] == [f"2026-{m:02d}" for m in range(1, 13)]
    assert fig["net12"][0] == 6302.0 and fig["net12"][1] == -900.0 and fig["net12"][2] == 0.0


def test_is_open_for_the_running_month_and_year():
    now = datetime(2026, 10, 14, tzinfo=UTC)
    assert planning.is_open("2026-10", now) and planning.is_open("2026-11", now) and not planning.is_open("2026-09", now)
    assert planning.is_open("2026", now) and planning.is_open("2027", now) and not planning.is_open("2025", now)


def test_open_period_stays_live_and_freezes_on_the_first_save_after_it_ends(store_db):
    seed_month()
    jan = datetime(2026, 1, 20, tzinfo=UTC)
    e = planning.save_entry("2026-01", "So far so good.", today=jan)
    assert e["figures"] is None and e["frozen_at"] is None
    v = planning.notebook_view("2026-01", today=jan)
    assert v["frozen"] is False and v["open"] is True and v["figures"]["expense"] == 1698.0
    with pytest.raises(DomainError) as exc:
        planning.refreeze("2026-01", today=jan)                      # nothing to refreeze while open
    assert exc.value.status == 409
    dbhelper.seed(transactions, [{"_id": "x9", "Date": datetime(2026, 1, 28), "Group": "Food",
                                        "Category": "Groceries", "Amount": -100.0, "Type": "Expense"}])
    assert planning.notebook_view("2026-01", today=jan)["figures"]["expense"] == 1798.0   # live moved
    e2 = planning.save_entry("2026-01", "So far so good. Then not.", today=datetime(2026, 2, 2, tzinfo=UTC))
    assert e2["figures"]["expense"] == 1798.0 and e2["frozen_at"].isoformat().startswith("2026-02-02")
    assert planning.notebook_view("2026-01", today=datetime(2026, 2, 3, tzinfo=UTC))["frozen"] is True


def test_entry_frozen_while_open_shows_live_and_unfreezes_on_save(store_db):
    """A row from before the amendment: frozen on the 8th of a month still running."""
    seed_month()
    stale = {**planning.figures_for("2026-01", today=datetime(2026, 1, 8, tzinfo=UTC)), "expense": 1.0}
    journal_entries.insert({"period": "2026-01", "body": "early", "figures": stale, "frozen_at": stale["frozen_at"]})
    jan = datetime(2026, 1, 20, tzinfo=UTC)
    assert planning.get_entry("2026-01", today=jan)["figures"] is None
    v = planning.notebook_view("2026-01", today=jan)
    assert v["frozen"] is False and v["figures"]["expense"] == 1698.0
    e = planning.save_entry("2026-01", "early, edited", today=jan)
    assert e["figures"] is None and journal_entries.for_period("2026-01")["figures"] is None
    # Closed and read back without a save: the stale freeze would show, which is why the save clears it.


def test_delete_entry_is_audited(store_db):
    planning.save_entry("2026-01", "bye")
    assert planning.delete_entry("2026-01") == {"ok": True, "period": "2026-01"}
    assert journal_entries.for_period("2026-01") is None
    logged = deletions.list({"collection": "journal_entries"})
    assert len(logged) == 1 and logged[0]["doc"]["body"] == "bye"
    with pytest.raises(DomainError):
        planning.delete_entry("2026-01")


def test_entry_rejects_bad_periods_and_bodies(store_db):
    for bad in ("2026-13", "garbage", "2026-1"):
        with pytest.raises(DomainError):
            planning.save_entry(bad, "x")
    with pytest.raises(DomainError):
        planning.save_entry("2026-01", "x" * (planning.BODY_LIMIT + 1))
    with pytest.raises(DomainError):
        planning.save_entry("2026-01", 5)  # type: ignore[arg-type]
    assert journal_entries.count() == 0


# --- prompts (D8) --------------------------------------------------------------------------

def test_prompt_rules_on_the_seeded_month(store_db):
    seed_month()
    dbhelper.seed(balance_history, [
        {"_id": "s1", "Date": datetime(2025, 12, 31), "Account": "Checking", "Class": "Asset", "Balance": 1000.0},
        {"_id": "s2", "Date": datetime(2026, 1, 31), "Account": "Checking", "Class": "Asset", "Balance": 1500.0},
    ])
    f = planning.month_facts("2026-01", today=datetime(2026, 2, 10, tzinfo=UTC))
    texts = {p["id"]: p["text"] for p in planning.prompts(f)}
    assert texts == {
        "unbudgeted:Dining": "Dining spent $210 with no budget line.",
        "over:Food": "Food ran 21% over: $1,455 vs $1,200.",
        "idle:Rent": "Rent had a $2,100 line and no activity.",          # Gifts' zero line stays silent
        "networth": "Net worth +$500 this month to $1,500.",
        "uncategorized": "1 transaction is still uncategorized.",
    }
    # Salary (income, actual-only) never prompts; a net worth measured in a fallback month
    # does not either.
    f2 = planning.month_facts("2026-03", today=datetime(2026, 3, 10, tzinfo=UTC))
    assert [p["id"] for p in planning.prompts(f2)] == ["uncategorized"]
    # While the month is still running, untouched lines are not yet "no activity".
    f3 = planning.month_facts("2026-01", today=datetime(2026, 1, 10, tzinfo=UTC))
    assert "idle:Rent" not in {p["id"] for p in planning.prompts(f3)}


def test_prompt_rules_are_silent_below_their_floors():
    facts = {"budget": {"rows": [
        {"group": "Coffee", "kind": "expense", "match": "actual_only", "actual_abs": 24.0, "budget_abs": 0.0, "over": 24.0},
        {"group": "Food", "kind": "expense", "match": "both", "actual_abs": 1100.0, "budget_abs": 1000.0, "over": 100.0},
        {"group": "Gifts", "kind": "expense", "match": "budget_only", "actual_abs": 0.0, "budget_abs": 0.0, "over": 0.0},
    ]}, "net_worth": {"delta": 10.0, "value": 100.0, "exact": False}, "uncategorized": 0}
    assert planning.prompts(facts) == []
    facts["uncategorized"] = 3
    assert planning.prompts(facts) == [{"id": "uncategorized", "text": "3 transactions are still uncategorized."}]


def test_streak_rule_needs_every_prior_month_over():
    row = lambda over: {"group": "Food", "kind": "expense", "match": "both", "actual_abs": 1000 + over,
                        "budget_abs": 1000.0, "over": float(over)}
    facts = {"budget": {"rows": [row(50)]}, "net_worth": None, "uncategorized": 0}
    prior_over = {"rows": [row(30)]}
    prior_under = {"rows": [row(0)]}
    assert [p["id"] for p in planning.prompts(facts, [prior_over, prior_over])] == ["streak:Food"]
    assert planning.prompts(facts, [prior_over, prior_over])[0]["text"] == "Food over budget 3 months running."
    assert planning.prompts(facts, [prior_over, prior_under]) == []
    assert planning.prompts(facts, [prior_over, None]) == []                 # a month with no budget breaks it
    assert planning.prompts(facts, [prior_over]) == []                       # not enough history


def test_month_prompts_reads_the_two_prior_budgets(store_db):
    seed_month()
    for ym, bid, date in (("2025-12", "bud_dec", datetime(2025, 12, 1, tzinfo=UTC)),
                          ("2025-11", "bud_nov", datetime(2025, 11, 1, tzinfo=UTC))):
        dbhelper.seed(budgets, [{"_id": bid, "budgetId": bid, "versionName": ym, "month": ym,
                                       "status": "saved", "_created_at": date}])
        dbhelper.seed(budget_lines, [{"budget": bid, "position": 0, "group": "Food", "amount": -1000}])
        dbhelper.seed(transactions, [{"_id": f"t{bid}", "Date": datetime(int(ym[:4]), int(ym[5:]), 10),
                                            "Group": "Food", "Category": "Groceries", "Amount": -1050.0, "Type": "Expense"}])
    f = planning.month_facts("2026-01", today=datetime(2026, 1, 10, tzinfo=UTC))
    ps = planning.month_prompts(f, "Food ran 21% over: $1,455 vs $1,200. Noted.")
    by = {p["id"]: p for p in ps}
    assert "streak:Food" in by and by["streak:Food"]["addressed"] is False
    assert by["over:Food"]["addressed"] is True                            # sentence occurs in the body
    assert by["unbudgeted:Dining"]["addressed"] is False


def test_addressed_folds_whitespace():
    ps = [{"id": "a", "text": "Food ran 21% over: $1,455 vs $1,200."}]
    assert planning.addressed(ps, "notes\n\nFood ran 21% over:\n$1,455 vs $1,200. ok")[0]["addressed"] is True
    assert planning.addressed(ps, "Food ran 20% over")[0]["addressed"] is False


# --- planned spend folded into the budget (#183) -------------------------------------------

def test_budget_report_folds_planned_spend_into_lines(store_db):
    from app import expected_flows as flows
    seed_month()
    flows.add_flow({"kind": "expense", "name": "Big dinner", "group": "Dining", "amount": 300,
                          "cadence": "once", "month": "2026-01"})
    flows.add_flow({"kind": "expense", "name": "Stock the pantry", "group": "Food", "amount": 400,
                          "cadence": "once", "anchor_date": "2026-01-20"})
    flows.add_flow({"kind": "expense", "name": "Next month", "group": "Dining", "amount": 50,
                          "cadence": "once", "month": "2026-02"})
    rep = planning.budget_report("2026-01", today=datetime(2026, 1, 10, tzinfo=UTC))
    by = {r["group"]: r for r in rep["rows"]}
    assert by["Dining"]["match"] == "both" and by["Dining"]["budget_abs"] == 300.0 and by["Dining"]["planned"] == 300.0
    assert by["Dining"]["pill"]["text"] != "unbudgeted"                     # it is budgeted now
    assert by["Food"]["budget_abs"] == 1600.0 and by["Food"]["planned"] == 400.0   # 1200 + 400
    assert by["Food"]["over"] == -145.0 and by["Food"]["pill"]["cls"] == "ok"      # 1455 vs 1600: within 10%
    assert rep["planned_total"] == 700.0 and rep["spend_budget"] == 3300.0 + 700.0
    # The stored budget is untouched and the unbudgeted prompt is quiet for Dining.
    assert len(budget_lines.for_budget("bud_a")) == 3
    f = planning.month_facts("2026-01", today=datetime(2026, 2, 10, tzinfo=UTC))
    ids = {p["id"] for p in planning.prompts(f)}
    assert "unbudgeted:Dining" not in ids and "over:Food" not in ids
