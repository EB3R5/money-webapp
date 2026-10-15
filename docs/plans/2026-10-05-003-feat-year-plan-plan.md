---
title: Year plan - Plan
type: feat
date: 2026-10-05
topic: year-plan
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Year plan - Plan

## Goal Capsule

- **Objective:** A twelve-month planner of **planned spend** — one-off and yearly expected
  outflows (vet, doctor, car repair, items decided in future-purchases) — showing when each
  lands, what it does to each month's net and to a projected P&L, and whether a savings goal
  funds it. Three pages under Planning ▾ (Year plan, Projected P&L, Calendar) over one set of
  facts; the Income sources registry generalises into Expected flows; future-purchases is
  pulled on demand.
- **Product authority:** #167 (#167) and
  ADR-0023; decisions chosen in dialogue on 2026-10-05.
- **Stop conditions:** none open.

## Context


The user wants a planner for the next twelve months of **planned spend**: one-off and yearly outflows such as a vet visit, a doctor visit, a car repair, and items decided in the future-purchases app. It should show when each lands, what it does to each month's net and to a projected P&L, and whether a savings goal funds it. A throwaway prototype outside the repo showed three layouts; the user wants all three built under Planning ▾, as with the first Planning prototype.

Decisions already made (2026-10-05):
- **Expected flows.** Generalise the Income sources registry into one table and module for typed expected money, income and expense, with cadences including "once", a ledger Group, an optional savings goal, and an origin (typed or future-purchases). The Income page becomes one view of it and keeps working.
- **Three pages**, one per layout: Year plan (timeline), Projected P&L, Calendar wall.
- **Base net** per month = expected income − recurring bills − variable spend − savings contribution (target rate × expected income). Planned spend subtracts from that; a negative month is flagged.
- **Pull on demand.** No timer, no push, no API keys. A button in the money app calls future-purchases over the compose network and upserts by external id. future-purchases has no JSON list endpoint today, so it gains one read-only route.

Repos: this one (migration 0017, ADR-0023) and future-purchases (FastAPI + Mongo, no auth). Both containers sit on the same compose default network; the service name is `future-purchases`, internal port 8000. Process convention: docs first, one PR per slice, each PR opened against main after the previous one merges (no stacking).

## Key Decisions

- **D1 One table, one module.** Migration 0017 creates `expected_flows`, copies `income_sources` into it (`kind='income'`, `origin='typed'`) and drops the old table. `app/income_sources.py` becomes `app/expected_flows.py` with no shim; the consumers (`app/planning.py`, `app/routers/planning.py`, `app/data_health.py`, tests) move in the same PR. `merged_sources(today)` reads `kind="income"` only; new `planned_spend(today)` reads active `kind="expense"` flows. The Income page, its three APIs and the Month template's `income_sources` key keep their names.
- **D2 Placement is the anchor.** `anchor_date` stays the one scheduling field. A month-only placement stores the first of the month with `day_known = 0` (pages print "Mar 2027"); a dated one stores the day with `day_known = 1`. `placed` is derived from `anchor_date IS NOT NULL`, never a column. Unplace = anchor NULL. New cadences: `once` (the anchor exactly once; no per-month figure; one occurrence only in its month), `bimonthly` (2 months), `semiyearly` (6 months), so future-purchases intervals map one to one.
- **D3 Window and base net.** The window is the 12 months **starting with the current month** (so a spend planned later this month is visible). Per month: `base_net = income − bills − variable − savings` (income from `merged_sources`, bills from `recurring.bills`, variable = `variable_daily × days_in`, savings = `target_rate × income`); `net = base_net − planned`; `flag = net < 0`. The current month is marked `partial` on the strip and is the actual column on the Projected P&L. Flows anchored before the window and not done are listed in a "dated earlier" strip (move or mark done). Double counting: `variable_daily_spend` already carries past lumpy spend; v1 subtracts nothing and labels every figure "estimated from ledger" (recorded in ADR-0023).
- **D4 Funding.** `savings_goals` gains `monthly_contribution` through its spill `data` JSON (no migration; `savings.update_goal` accepts it; `list_goals` rows carry it; default 0; the Savings page field is a follow-up). Coverage for a placed item at window index `i`: `avail = max(0, goal.current_balance + monthly_contribution × (i + 1) − earlier_earmarked)`, `covered = min(amount, avail)`, `pct = min(1, avail ÷ amount)`, the prototype's rule. The funds panel shows have-now, per month, earmarked this window, balance by the window end, "short" when earmarked exceeds it.
- **D5 Pull on demand; hand edits win per field.** future-purchases exposes read-only `GET /api/planned`. The money app calls it only when the button is pressed; `FUTURE_PURCHASES_URL` unset means the button says "not configured". Upsert by `external_id`. Interval → cadence: Semi-monthly → `biweekly` (future-purchases defines it as 14 days), Monthly → `monthly`, Bi-monthly → `bimonthly`, Quarterly → `quarterly`, Semi-annual → `semiyearly`, Annual → `yearly`. Group: the future-purchases category's Group when it names a ledger Group, else the Category when it does, else "Planned". Each pulled row keeps a `pulled` JSON snapshot of what the feed last said; a field is overwritten only when its current value still equals the snapshot (ADR-0019's rule in one column), so an amount, month, group, goal or name the person changed survives later pulls. Items no longer decided or active → `active = 0` with `external_status` recorded, never deleted; they come back by the same rule. Every pull logs a `sync_runs` row with `feed = "future-purchases"`. The page head shows the last run; a page render never calls the other service.
- **D6 Projected P&L is its own page.** `/planning/projected` tabulates with `app/pivot.pivot` over string column keys (`YYYY-MM`) and a `col_kind` map; `reports.pnl` and `pnl.html` are untouched. The actual column: income from `rollup.income_expense`, bills as the series expect, variable = actual expense − bills (floored at 0), planned rows from placed flows in that month, savings = target rate × actual income.
- **D7 Server renders, JS enhances.** Each page is rendered by Jinja from `year_plan()` / `projected_pnl()`; the same facts are embedded as `<script type="application/json" id="plan-data">` for the detail card, move warnings and shelf-to-month placement; every write posts JSON then reloads (the Income page's pattern). Widths through `data-w` (the CSP forbids style attributes).

## Product Contract

### Summary

| Route | Behaviour |
|---|---|
| `GET /planning/year` | `planning_year.html`: head (window label, summary, last pull, **Sync future-purchases**, **Add planned spend**), 12 columns of pins with funding bars and month net (red when negative), detail card (group, cadence, origin, funding, net with it, "Move to" buttons with ⚠ when the target goes negative), affordability list, "dated earlier" strip, add form |
| `GET /planning/projected` | `planning_projected.html`: current month actual + 11 dashed projected columns; sections Income (Income sources), Spend (Recurring bills, Variable spend), Planned (one `Planned · <Group>` row each), Savings (Savings contribution); Net after savings row with red cells; Year total column; click a planned cell → move picker |
| `GET /planning/calendar` | `planning_calendar.html`: 12 month cards (net, base line, items with ✕ to unplace, planned total, red border), the shelf (click one, then a month), the funds panel |
| `POST /api/planning/flows` | add planned spend: `{name, group, amount, cadence, anchor_date? or month?, goal_id?, notes?}` → `{ok, id}` (kind forced `expense`) |
| `POST /api/planning/flows/update` | dirty-diff by `id`: `month` (`YYYY-MM` places on the 1st with `day_known = 0`; `null` unplaces), `anchor_date`, `group`, `goal_id`, `amount`, `cadence`, `name`, `notes`, `active` |
| `POST /api/planning/flows/delete` | audited delete (ADR-0005) |
| `POST /api/planning/flows/{id}/done` | `done_at = today` (manual for now); a done flow leaves the window |
| `POST /api/planning/sync/future-purchases` | runs `pull()`; JSON `{ok, run_id, status, created, updated, withdrawn, error}`; `?next=` redirects with `?sync=<status>`; 503 "not configured" when the URL is unset |
| `GET /api/planning/year` | `year_plan()` as JSON |
| `GET /api/planned` (future-purchases) | `{generated_at, purchases: [{res_id, item_name, category, group, est_cost, target_date, status, priority, edited_at}], recurring: [{rec_id, item_name, category, group, est_cost, interval, interval_days, last_restocked, next_due, edited_at}]}`: decided purchases with a cost; active recurring with a cost and an Interval |

Nav: Planning ▾ = Month, Notebook, Planner, Income, **Year plan**, **Projected P&L**, **Calendar**. Validation: name required; amount positive; cadence in `CADENCES`; group a non-blank string; `goal_id` an existing goal; `month` passes `planning.is_month`.

### Data

**Migration `app/store/schema/0017_expected_flows.sql`**: `expected_flows(id, kind NOT NULL, name NOT NULL, category, "group", cadence NOT NULL, amount REAL NOT NULL, anchor_date, day_known INTEGER NOT NULL DEFAULT 1, goal_id, origin NOT NULL DEFAULT 'typed', external_id, external_status, pulled TEXT, priority, done_at, done_txn, active INTEGER NOT NULL DEFAULT 1, notes, created_at, edited_at)`; indexes on `kind`, `category`, `"group"`, a unique partial index on `external_id`; `INSERT … SELECT` from `income_sources`; `DROP TABLE income_sources`. `tests/test_store.py`: `LATEST = 17`, table name swapped. Data-health section "Expected flows" (`date_col` `anchor_date`). Regenerate `docs/schema.mmd`.

**`app/store/expected_flows.py`**: `ExpectedFlowsStore` with `active(kind)`, `by_external_id(external_id)`, `pulled()`; Field kinds: `pulled` json, `done_at` date, `anchor_date` date, `day_known`/`active` bool.

**`app/expected_flows.py`** (from `income_sources.py`): `KINDS`, `CADENCES = ("once", "weekly", "biweekly", "semimonthly", "monthly", "bimonthly", "quarterly", "semiyearly", "yearly", "irregular")`, `PER_MONTH`, `PERIOD_DAYS`, origins `TYPED / PULLED / DETECTED` (stepping dispatches on `origin != DETECTED`), `occurrences`, `next_date`, `registry_due_dates`, `registry_occurrences_in_month`, `as_series(flow, today)` (adds `kind, group, goal_id, origin, external_id, external_status, day_known, month, placed, done_at, priority`), `due_dates`, `occurrences_in_month`, `planned_in_month(series, ym) -> float`, `merged_sources(today)`, `planned_spend(today)`, `income_categories`, `list_flows(kind, today)`, `add_flow(body)`, `update_flow(body)` (accepts `month`), `delete_flow(body)`, `mark_done(flow_id, today)`.

**`app/planning.py` additions**: `WINDOW_MONTHS = 12`, `plan_months(today) -> list[str]` (current month first), `base_month(ym, income_series, bill_series, variable_daily, target_rate) -> dict`, `funding(item, goal, index, earlier_earmarked) -> dict | None` (pure), `year_plan(today=None) -> {start, end, months: [{month, label, kind: partial|expected, income, bills, variable, savings, base_net, planned, net, flag, items: [{id, name, group, amount, cadence, origin, external_id, goal_id, funding, day_known}]}], shelf, past, funds: [{id, name, have, per, earmarked, by_end, short}], groups, totals: {planned, flagged, unplaced}, last_pull, estimates}`, `projected_pnl(today=None) -> {columns, col_kind, table (pivot result), net: {by_col, total}, flags}`; `project(…, planned_series=())` adds planned events as outflows and `forecast` passes `planned_spend`.

**`app/future_purchases.py`**: `FuturePurchasesError(DomainError)`, `INTERVAL_CADENCE`, `fetch_planned(base_url, *, transport=None, timeout=10.0) -> dict` (httpx with the transport seam, errors mapped), `group_for(fp_group, fp_category, ledger_groups) -> str`, `to_flow(item, ledger_groups) -> dict` (pure), `merge(current, incoming) -> dict` (the per-field snapshot rule, pure), `pull(today=None, *, transport=None, trigger="ui") -> dict` (sync_runs lifecycle mirrored from `app/simplefin/sync.py`). `config.FUTURE_PURCHASES_URL`.

**future-purchases `app/routers/planned.py`**: pure `purchase_row(doc, gmap)`, `recurring_row(doc, gmap)` (Group from the categories collection; `next_due` via `recurring_item.next_due`), handler `planned()`, registered in `ROUTER_MODULES` before `purchases`.

## Slices (as built, 2026-10-05 → 06)

One PR per slice against `main`, each opened after the previous merged (no stacking).
Parent #167 (#167).

1. **future-purchases: read-only planned export** (future-purchases#6) — `GET /api/planned`,
   `tests/test_planned.py`, the **Planned export** glossary term — future-purchases PR #7.
2. **Docs first: ADR-0023 and glossary** (#168) — PR #175.
3. **Expected flows generalisation** (#169) — migration 0017, `app/expected_flows.py`,
   `app/store/expected_flows.py`, consumers, `savings.update_goal` / `list_goals` with
   `monthly_contribution`, `tests/test_expected_flows.py` incl. a migration test — PR #176.
4. **Year plan facts and page** (#170) — `plan_months`, `base_month`, `funding`, `year_plan`,
   `project(planned_series)`, `/planning/year`, the flow APIs, `tests/test_planning_year.py` — PR #177.
5. **Pull on demand** (#171) — `app/future_purchases.py`, `POST /api/planning/sync/future-purchases`,
   the Activity feed column and form, `docs/deployment.md`, `tests/test_future_purchases.py` — PR #178.
6. **Projected P&L page** (#172) — `planning.projected_pnl`, `/planning/projected`,
   `tests/test_planning_projected.py` — PR #179.
7. **Calendar page** (#173) — `/planning/calendar`, `tests/test_planning_calendar.py` — PR #180.
8. **Close-out** (#174) — this PR; the production compose gained `FUTURE_PURCHASES_URL` for money-next.

Full suite after slice 7: 799 passed, 1 skipped; `schema_doc.py --check` green.

Deviations from the contract above, each recorded in its PR:

- Calendar stepping applies to the two registry origins (typed, future-purchases); a series
  without one steps like the detector. A first draft stepped everything not tagged detected
  by the calendar and caught the bill series (slice 3).
- The `sync_runs` table constrains `trigger` to scheduler/startup/manual/cli, so a pull logs
  `manual` rather than `ui` (slice 5).
- The Calendar's earlier-than-window strip links to the Year plan rather than offering move
  or done in place; its page tests seed relative to the clock instead of reusing the Year
  plan's fixed-date seed (slice 7).
- A pulled item whose Group fell back to "Planned" shows as "Planned · Planned" on the
  Projected P&L (slice 6).
- The three page slices were built in parallel and appended to the same four files; each
  merge needed a keep-both rebase of the rest (nav line, end-of-file appends).

Follow-ups filed: #181 reconciliation, #182 per-goal balances and the Savings page field,
#183 a planned line in budgets, #184 drag-and-drop and a start month, #185 netting matched
lumpy spend out of the variable rate.

## Verification

- `./.venv/bin/python -m pytest -q` green in both repos per slice; `scripts/schema_doc.py --check` after slice 3.
- On a **copy** of the live data (scratch launcher, auth off): the Income page still lists every source after migration 0017; add a once "Dentist · crown" with a month only and a yearly "Car registration" with a date; see the pins, the net, a red month after moving a big item, and the forecast dip on its day.
- With `FUTURE_PURCHASES_URL=http://127.0.0.1:8020` against the real future-purchases (read-only GET), press **Sync future-purchases**, confirm the counts on Activity and the decided items on the shelf or in their month; edit a pulled amount, pull again, it stays.
- Screenshots of each page at desktop width on its PR; the closeout set (Year plan, Projected P&L, Calendar, Income) is on PR #186. Prod rebuild only when asked, through the homelab compose project; `FUTURE_PURCHASES_URL` is in the compose (homelab edae38d).

## Follow-ups (built 2026-10-06)

#181–#185 all merged the next day (PRs #189–#192), plus: the Pull widened to open items with a
cost (future-purchases #10, money #194) after decided-only found nothing, and a search box on
the four planned-spend pages (#195).

## Follow-ups as first written

- Auto-reconciliation: match a planned spend to a ledger transaction (amount, Group, date window), mark it done and flip the future-purchases item to ordered.
- Per-goal balances (today `current_balance` is the pooled total); the Savings page field for `monthly_contribution`.
- Budgets gain a planned line per Group; drag-and-drop on the calendar; a start-month parameter.
- Subtracting matched lumpy spend from `variable_daily_spend` once reconciliation exists.
- Deleting the year-planner prototype once a layout wins, recording the verdict. The pull has
  been exercised against mocked responses only; the first real pull happens after the rebuild.
