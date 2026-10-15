"""Income sources (app/income_sources.py, ADR-0022): calendar stepping per cadence, the
conversion to the detector's series shape, the merge with detection, the registry CRUD with
its validation and audited delete, and the Income page."""

from datetime import UTC, date, datetime

import pytest

from app import expected_flows as inc
from app.store.categories import categories
from app.store.deletions import deletions
from app.store.expected_flows import expected_flows as income_sources
from app.store.transactions import transactions
from app.web import DomainError
from tests import dbhelper

TODAY = date(2026, 10, 5)


def test_add_months_clamps_to_month_end():
    assert inc.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert inc.add_months(date(2026, 1, 31), 2) == date(2026, 3, 31)
    assert inc.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_next_date_per_cadence():
    assert inc.next_date("biweekly", date(2026, 9, 25), TODAY) == date(2026, 10, 9)
    assert inc.next_date("monthly", date(2026, 8, 31), TODAY) == date(2026, 10, 31)
    assert inc.next_date("quarterly", date(2026, 1, 15), TODAY) == date(2026, 10, 15)
    assert inc.next_date("yearly", date(2025, 3, 1), TODAY) == date(2027, 3, 1)
    assert inc.next_date("weekly", date(2026, 10, 20), TODAY) == date(2026, 10, 20)   # anchor ahead stays
    assert inc.next_date("irregular", date(2026, 10, 1), TODAY) is None
    assert inc.next_date("monthly", None, TODAY) is None


def test_semimonthly_pairs_days_and_clamps():
    # anchor on the 1st → 1st and 16th; anchor on the 20th → 5th and 20th
    assert inc.registry_due_dates("semimonthly", date(2026, 10, 1), date(2026, 9, 30), date(2026, 11, 30)) == [
        date(2026, 10, 1), date(2026, 10, 16), date(2026, 11, 1), date(2026, 11, 16)]
    assert inc.registry_due_dates("semimonthly", date(2026, 10, 20), date(2026, 10, 19), date(2026, 11, 30)) == [
        date(2026, 10, 20), date(2026, 11, 5), date(2026, 11, 20)]              # nothing before the anchor
    # 15th + 15 = 30th, clamped in February
    assert inc.registry_due_dates("semimonthly", date(2026, 1, 15), date(2026, 1, 31), date(2026, 2, 28)) == [
        date(2026, 2, 15), date(2026, 2, 28)]


def test_occurrences_in_month_per_cadence():
    assert inc.registry_occurrences_in_month("semimonthly", date(2026, 10, 1), "2026-11") == 2
    assert inc.registry_occurrences_in_month("biweekly", date(2026, 10, 2), "2026-10") == 3    # 2, 16, 30
    assert inc.registry_occurrences_in_month("monthly", date(2026, 10, 31), "2026-11") == 1    # clamped to the 30th
    assert inc.registry_occurrences_in_month("monthly", date(2026, 10, 31), "2026-09") == 0    # before the anchor
    assert inc.registry_occurrences_in_month("quarterly", date(2026, 1, 15), "2026-07") == 1
    assert inc.registry_occurrences_in_month("quarterly", date(2026, 1, 15), "2026-08") == 0
    assert inc.registry_occurrences_in_month("irregular", date(2026, 1, 1), "2026-01") == 0


def test_as_series_shape_and_dispatch():
    src = {"_id": "s1", "name": "Paycheck", "category": "Salary", "cadence": "semimonthly",
           "amount": 3420.0, "anchor_date": date(2026, 10, 1), "active": True}
    s = inc.as_series(src, TODAY)
    assert s["origin"] == "typed" and s["key"] == "typed:s1" and s["label"] == "Paycheck"
    assert s["next_date"] == "2026-10-16" and s["per_month"] == 6840.0 and s["stable"] is True
    assert s["period_days"] == pytest.approx(15.22) and s["first_date"] == "2026-10-01"
    assert inc.occurrences_in_month(s, "2026-11") == 2
    assert inc.due_dates(s, date(2026, 10, 5), date(2026, 10, 31)) == [date(2026, 10, 16)]
    # A detected series keeps the detector's stepping.
    det = {"origin": "detected", "cadence": "monthly", "period_days": 30.44, "next_date": "2026-10-20",
           "first_date": "2026-05-20", "last_date": "2026-09-20"}
    assert inc.due_dates(det, date(2026, 10, 5), date(2026, 11, 30)) == [date(2026, 10, 20), date(2026, 11, 19)]
    assert inc.occurrences_in_month(det, "2026-11") == 1
    irregular = inc.as_series({"_id": "s2", "name": "Gifts", "cadence": "irregular", "amount": 50.0}, TODAY)
    assert irregular["next_date"] is None and irregular["per_month"] is None and irregular["period_days"] is None


def _seed_income_ledger():
    dbhelper.seed(categories, [
        {"_id": "Salary", "Category": "Salary", "Group": "Work", "Type": "Income"},
        {"_id": "Dividends", "Category": "Dividends", "Group": "Investing", "Type": "Income"},
        {"_id": "Rent", "Category": "Rent", "Group": "Housing", "Type": "Expense"},
    ])
    rows = []
    for i, (y, m) in enumerate([(2026, 7), (2026, 8), (2026, 9)]):
        rows.append({"_id": f"sal{i}", "Date": datetime(y, m, 1), "Category": "Salary", "Amount": 5000.0, "Type": "Income"})
        rows.append({"_id": f"div{i}", "Date": datetime(y, m, 10), "Category": "Dividends", "Amount": 40.0, "Type": "Income"})
    dbhelper.seed(transactions, rows)


def test_merged_sources_typed_first_then_unclaimed_detected(store_db):
    _seed_income_ledger()
    inc.add_source({"name": "Paycheck", "category": "Salary", "cadence": "semimonthly",
                          "amount": 2500, "anchor_date": "2026-10-01"})
    inc.add_source({"name": "Old job", "category": "Dividends", "cadence": "monthly",
                          "amount": 1, "anchor_date": "2026-10-01", "active": False})
    merged = inc.merged_sources(datetime(2026, 10, 5, tzinfo=UTC))
    assert [(s["label"], s["origin"]) for s in merged] == [("Paycheck", "typed"), ("Dividends", "detected")]
    # Salary is claimed by the typed source; Dividends is not (the inactive source does not claim).
    assert merged[1]["cadence"] == "monthly" and merged[1]["amount"] == 40.0


def test_add_update_delete_with_validation_and_audit(store_db):
    _seed_income_ledger()
    r = inc.add_source({"name": " Paycheck ", "category": "Salary", "cadence": "Biweekly",
                              "amount": "3,420.50", "anchor_date": "2026-10-09", "notes": " two a month "})
    row = income_sources.get(r["id"])
    assert row["name"] == "Paycheck" and row["cadence"] == "biweekly" and row["amount"] == 3420.5
    assert row["anchor_date"].isoformat()[:10] == "2026-10-09" and row["notes"] == "two a month" and row["active"] is True
    for bad in ({"name": "", "cadence": "monthly", "amount": 1},
                {"name": "x", "cadence": "fortnightly", "amount": 1},
                {"name": "x", "cadence": "monthly", "amount": 0},
                {"name": "x", "cadence": "monthly", "amount": 1, "anchor_date": "soon"},
                {"name": "x", "cadence": "monthly", "amount": 1, "category": "Nope"}):
        with pytest.raises(DomainError):
            inc.add_source(bad)
    assert income_sources.count() == 1
    inc.update_source({"id": r["id"], "active": False, "amount": 3500, "category": ""})
    row = income_sources.get(r["id"])
    assert row["active"] is False and row["amount"] == 3500.0 and row["category"] is None
    with pytest.raises(DomainError):
        inc.update_source({"id": r["id"], "name": "  "})
    with pytest.raises(DomainError):
        inc.update_source({"id": "missing", "name": "x"})
    assert inc.delete_source({"id": r["id"]}) == {"ok": True, "deleted": 1}
    logged = deletions.list({"collection": "expected_flows"})
    assert len(logged) == 1 and logged[0]["doc"]["name"] == "Paycheck"
    assert inc.list_sources() == []


def test_income_page_and_api(store_client):
    _seed_income_ledger()
    html = (store_client.get("/planning/income")).text
    assert "<h1>Income sources</h1>" in html and "No income sources yet" in html
    assert 'data-detected="Salary"' in html and 'data-detected="Dividends"' in html     # both detected, none claimed
    assert '<option value="Salary">' in html and '<option value="Rent">' not in html      # Income categories only
    assert '<option value="semimonthly">' in html and 'href="/planning/income"' in html   # nav link
    r = store_client.post("/api/planning/income", json={"name": "Paycheck", "category": "Salary",
                                                             "cadence": "semimonthly", "amount": 2500, "anchor_date": "2026-10-01"})
    assert r.status_code == 200 and r.json()["ok"]
    sid = r.json()["id"]
    html = (store_client.get("/planning/income")).text
    assert f'data-source-id="{sid}"' in html and "$2,500" in html and "$5,000" in html     # amount and per month
    assert 'data-detected="Salary"' not in html and 'data-detected="Dividends"' in html   # Salary now claimed
    assert "1 active" in html
    r = store_client.post("/api/planning/income/update", json={"id": sid, "active": False})
    assert r.json()["ok"]
    html = (store_client.get("/planning/income")).text
    assert "0 active" in html and 'class="pill none">inactive' in html and 'data-detected="Salary"' in html
    assert (store_client.post("/api/planning/income", json={"name": "", "cadence": "monthly", "amount": 1})).status_code == 400
    r = store_client.post("/api/planning/income/delete", json={"id": sid})
    assert r.json() == {"ok": True, "deleted": 1}
    assert (store_client.post("/api/planning/income/delete", json={"id": sid})).status_code == 404


# --- the consumers read the merged list (slice 2, #163) ------------------------------------

from app import planning  # noqa: E402
from app.store.accounts import accounts  # noqa: E402


def test_month_income_table_typed_source_replaces_detected(store_db):
    _seed_income_ledger()
    today = datetime(2026, 10, 5, tzinfo=UTC)
    dbhelper.seed(transactions, [{"_id": "sal_oct", "Date": datetime(2026, 10, 1), "Category": "Salary",
                                        "Amount": 5000.0, "Type": "Income"}])
    before = {r["source"]: r for r in (planning.income_table("2026-10", today))["rows"]}
    assert before["Salary"]["origin"] == "detected" and before["Salary"]["expected"] == 5000.0
    inc.add_source({"name": "Paycheck", "category": "Salary", "cadence": "semimonthly",
                          "amount": 2600, "anchor_date": "2026-10-01"})
    t = planning.income_table("2026-10", today)
    by = {r["source"]: r for r in t["rows"]}
    assert "Salary" not in by                                               # claimed by the typed source
    assert by["Paycheck"]["origin"] == "typed" and by["Paycheck"]["cadence"] == "semimonthly"
    assert by["Paycheck"]["expected"] == 5200.0 and by["Paycheck"]["received"] == 5000.0  # 2 × 2600; the ledger's October
    assert by["Paycheck"]["next"] == "2026-10-16"
    assert by["Dividends"]["origin"] == "detected"
    assert t["expected_total"] == 5240.0                                    # 5200 + the detected 40


def test_year_facts_and_forecast_read_the_merged_list(store_db):
    _seed_income_ledger()
    today = datetime(2026, 10, 5, tzinfo=UTC)
    dbhelper.seed(accounts, [{"_id": "a1", "Account": "Checking", "Category": "Checking Account", "Amount": 1000.0}])
    inc.add_source({"name": "Paycheck", "category": "Salary", "cadence": "biweekly",
                          "amount": 2000, "anchor_date": "2026-10-09"})
    inc.add_source({"name": "Side gig", "cadence": "monthly", "amount": 300, "anchor_date": "2026-10-20"})
    inc.add_source({"name": "Old job", "category": "Dividends", "cadence": "monthly", "amount": 999,
                          "anchor_date": "2026-10-01", "active": False})
    y = planning.year_facts("2026", today=today)
    by = {s["source"]: s for s in y["expected_income"]}
    assert by["Paycheck"]["origin"] == "typed" and by["Paycheck"]["received_ytd"] == 15000.0   # Salary's actual
    assert by["Paycheck"]["expected_year"] == 2000.0 * 6                    # 9 Oct, 23 Oct, 6/20 Nov, 4/18 Dec
    assert by["Side gig"]["received_ytd"] == 0.0 and by["Side gig"]["expected_year"] == 900.0   # no category
    assert by["Dividends"]["origin"] == "detected"                         # the inactive source claims nothing
    assert "Old job" not in by
    nov = next(m for m in y["months"] if m["month"] == "2026-11")
    assert nov["kind"] == "expected" and nov["income"] == 2000.0 * 2 + 300.0 + 40.0
    f = planning.forecast(today=today, days=30)
    labels = [(e["date"], e["label"], e["amount"]) for e in f["events"] if e["amount"] > 0]
    assert ("2026-10-09", "Paycheck", 2000.0) in labels and ("2026-10-23", "Paycheck", 2000.0) in labels
    assert ("2026-10-20", "Side gig", 300.0) in labels
    assert not any(e["label"] == "Old job" for e in f["events"])


def test_planner_and_month_pages_mark_detected_rows(store_client):
    _seed_income_ledger()
    from app.budgets import current_month
    cur = current_month()
    inc.add_source({"name": "Paycheck", "category": "Salary", "cadence": "monthly", "amount": 5000,
                          "anchor_date": f"{cur}-28"})
    html = (store_client.get(f"/planning/planner/{cur[:4]}")).text
    assert 'data-source="Paycheck" data-origin="typed"' in html
    assert 'data-source="Dividends" data-origin="detected"' in html and 'class="pill none">detected' in html
    assert 'href="/planning/income"' in html
    html = (store_client.get(f"/planning/month/{cur}")).text
    assert 'data-source="Paycheck" data-cadence="monthly" data-origin="typed"' in html


# --- Expected flows (ADR-0023): both kinds, the new cadences, placement, done ----------------

from app.store.savings_goals import savings_goals  # noqa: E402
from app import savings  # noqa: E402


def test_once_bimonthly_semiyearly_step_by_the_calendar():
    assert list(inc.occurrences("once", date(2027, 3, 14))) == [date(2027, 3, 14)]
    assert inc.next_date("once", date(2027, 3, 14), date(2027, 3, 1)) == date(2027, 3, 14)
    assert inc.next_date("once", date(2027, 3, 14), date(2027, 3, 15)) is None        # its day has passed
    assert inc.registry_occurrences_in_month("once", date(2027, 3, 14), "2027-03") == 1
    assert inc.registry_occurrences_in_month("once", date(2027, 3, 14), "2027-04") == 0
    assert inc.next_date("bimonthly", date(2026, 10, 31), date(2026, 11, 1)) == date(2026, 12, 31)
    assert inc.registry_due_dates("bimonthly", date(2026, 10, 31), date(2026, 10, 31), date(2027, 4, 30)) == [
        date(2026, 12, 31), date(2027, 2, 28), date(2027, 4, 30)]
    assert inc.registry_due_dates("semiyearly", date(2026, 1, 15), date(2026, 1, 15), date(2027, 1, 31)) == [
        date(2026, 7, 15), date(2027, 1, 15)]
    assert inc.PER_MONTH["bimonthly"] == 0.5 and inc.PER_MONTH["semiyearly"] == 1 / 6


def test_as_series_planning_fields_and_planned_in_month():
    once = inc.as_series({"_id": "p1", "kind": "expense", "name": "Vet", "group": "Pet", "cadence": "once",
                          "amount": 600.0, "anchor_date": date(2027, 3, 1), "day_known": False,
                          "goal_id": "g1", "origin": "typed"}, TODAY)
    assert once["kind"] == "expense" and once["group"] == "Pet" and once["goal_id"] == "g1"
    assert once["placed"] is True and once["month"] == "2027-03" and once["day_known"] is False
    assert once["per_month"] is None and once["next_date"] == "2027-03-01"
    assert inc.planned_in_month(once, "2027-03") == 600.0 and inc.planned_in_month(once, "2027-04") == 0.0
    pulled = inc.as_series({"_id": "p2", "kind": "expense", "name": "Laptop", "group": "Equipment",
                            "cadence": "once", "amount": 2400.0, "origin": "future-purchases",
                            "external_id": "RES-027", "external_status": "decided"}, TODAY)
    assert pulled["placed"] is False and pulled["month"] is None and pulled["key"] == "future-purchases:p2"
    assert pulled["external_id"] == "RES-027" and inc.planned_in_month(pulled, "2027-03") == 0.0
    # A detected bill series (no origin) still steps like the detector.
    bill = {"cadence": "monthly", "period_days": 30.44, "next_date": "2026-10-20", "first_date": "2026-05-20",
            "last_date": "2026-09-20", "amount": 50.0}
    assert inc.occurrences_in_month(bill, "2026-11") == 1


def test_add_flow_placement_kinds_goal_and_done(store_db):
    _seed_income_ledger()
    g = savings.add_goal({"name": "Pet fund", "target_amount": 1000})
    with pytest.raises(DomainError):
        inc.add_flow({"kind": "expense", "name": "Vet", "cadence": "once", "amount": 600})   # no group
    with pytest.raises(DomainError):
        inc.add_flow({"kind": "expense", "name": "Vet", "group": "Pet", "cadence": "once", "amount": 600,
                            "goal_id": "nope"})
    with pytest.raises(DomainError):
        inc.add_flow({"kind": "expense", "name": "Vet", "group": "Pet", "cadence": "once", "amount": 600,
                            "month": "2027-13"})
    r = inc.add_flow({"kind": "expense", "name": "Vet", "group": "Pet", "cadence": "once", "amount": 600,
                            "month": "2027-03", "goal_id": g["id"]})
    row = income_sources.get(r["id"])
    assert row["kind"] == "expense" and row["anchor_date"].isoformat()[:10] == "2027-03-01"
    assert row["day_known"] is False and row["goal_id"] == g["id"] and row["origin"] == "typed"
    # Placed by date → day known; unplace by month null; income flows never show as planned spend.
    inc.update_flow({"id": r["id"], "anchor_date": "2027-03-14"})
    assert (income_sources.get(r["id"]))["day_known"] is True
    inc.update_flow({"id": r["id"], "month": None})
    assert (income_sources.get(r["id"]))["anchor_date"] is None
    inc.add_source({"name": "Paycheck", "category": "Salary", "cadence": "monthly", "amount": 5000,
                          "anchor_date": "2026-11-01"})
    spend = inc.planned_spend(datetime(2026, 10, 5, tzinfo=UTC))
    assert [s["label"] for s in spend] == ["Vet"] and spend[0]["placed"] is False
    assert [s["label"] for s in inc.merged_sources(datetime(2026, 10, 5, tzinfo=UTC))][0] == "Paycheck"
    assert [s["kind"] for s in inc.list_flows("income")] == ["income"]
    inc.mark_done(r["id"], datetime(2026, 10, 5, tzinfo=UTC))
    assert (income_sources.get(r["id"]))["done_at"].isoformat()[:10] == "2026-10-05"
    assert inc.planned_spend(datetime(2026, 10, 5, tzinfo=UTC)) == []


def test_goal_monthly_contribution_lives_in_the_spill(store_db):
    g = savings.add_goal({"name": "Car fund", "target_amount": 3000})
    savings.update_goal({"id": g["id"], "monthly_contribution": "150"})
    [row] = savings.list_goals(2026)
    assert row["monthly_contribution"] == 150.0
    with pytest.raises(DomainError):
        savings.update_goal({"id": g["id"], "monthly_contribution": -5})
    assert (savings_goals.get(g["id"]))["monthly_contribution"] == 150.0         # the spill column


def test_migration_0017_copies_income_sources(tmp_path):
    """A pre-0017 database with income_sources rows comes out with the same rows as income
    flows and no income_sources table."""
    import importlib
    import sqlite3
    dbmod = importlib.import_module("app.store.database")
    data = tmp_path / "data"; data.mkdir()
    db_path = data / "money.sqlite"
    schema_dir = dbmod.SCHEMA_DIR
    with sqlite3.connect(db_path) as conn:
        for f in sorted(schema_dir.glob("*.sql")):
            if int(f.name.split("_")[0]) > 16:
                break
            conn.executescript(f.read_text())
            conn.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, '2026')", (int(f.name.split("_")[0]),))
        conn.execute("INSERT INTO income_sources(id, name, category, cadence, amount, anchor_date, active, notes) "
                     "VALUES ('s1', 'Paycheck', 'Salary', 'semimonthly', 2500, '2026-10-01', 1, 'two a month')")
        conn.commit()
    conn.close()
    db = dbmod.Database(data)
    assert db.init() == 18
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT kind, name, category, cadence, amount, anchor_date, day_known, origin, active FROM expected_flows").fetchall()
        assert rows == [("income", "Paycheck", "Salary", "semimonthly", 2500.0, "2026-10-01", 1, "typed", 1)]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "income_sources" not in tables
    conn.close()
