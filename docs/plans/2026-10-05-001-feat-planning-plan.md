---
title: Planning section - Plan
type: feat
date: 2026-10-05
topic: planning
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Planning section - Plan

## Goal Capsule

- **Objective:** A `Planning ▾` section with three pages over one month's planning data —
  Month (figures first), Notebook (prose with pinned Figure blocks), Planner (year strip,
  Checking forecast, expected income, sinking funds) — sharing one Journal entry per period.
  Real data where it exists (ledger, Budgets, Snapshots, savings goals); derived estimates
  elsewhere (Recurring series, the forecast, future months), always labelled "estimated from
  ledger". All three layouts ship so one can be chosen after living with them.
- **Product authority:** This document and ADR-0021. Decisions confirmed in dialogue
  2026-10-05 over a throwaway prototype of the three layouts, kept outside the repo.
  Execution parent: #140; slices #141–#150.
- **Stop conditions:** none open.

## Key Decisions

- **D1 One record, three layouts.** `journal_entries` holds one row per `period` (`YYYY-MM`
  or `YYYY`): Markdown `body` + `figures` JSON frozen at first save + `frozen_at`. A Refreeze
  action recomputes them. All three pages read and write the same row. The year review is in
  scope minimally: `/planning/notebook/{YYYY}` renders the same editor with year figures.
- **D2 Net worth has one owner.** The balance sheet's `_canon_class`, `_month_rows` and
  `CLASS_ORDER` move to `app/networth.py` with `summarize(rows)`, `net_worth_at(ym)` and
  `net_worth_delta(ym)`; the balance sheet imports them and its figures do not change. A month
  with no Snapshots falls back to the latest earlier month and reports `as_of`.
- **D3 Net savings rate = net ÷ income**, target from `savings.get_savings_config()
  .target_rate`. The Savings page's mapping-driven rate stays a separate, named concept.
- **D4 Budget for a month** = newest `status=saved` version for that month, else the newest
  draft, else none ("no budget" sub-line). Rows via `budgets.build_report`.
- **D5 Recurring detection is a pure function** (`app/recurring.py`) over `[{date, amount,
  key, label}]`; async loaders only select rows. Nothing stored; recomputed per request.
- **D6 The forecast is an estimate.** Start balance = Σ `accounts.Amount` of the checking
  accounts (`Category` or `Account Type` = "Checking Account", not Closed, not hidden); events
  from Recurring series projected forward; variable daily spend = (trailing-90-day Expense −
  recurring bills) ÷ 90.
- **D7 Markdown, one textarea.** Month and Planner edit a plain textarea. The Notebook renders
  Markdown (`documents.render_markdown`) with a `?edit=1` Write mode like `document.html`,
  preview via the existing `POST /api/documents/render`. Figure blocks render at `[[figures]]`
  and `[[misses]]` marker lines; absent markers put figures before the prose and misses after.
  No contenteditable.
- **D8 Prompts are addressed by text.** A prompt is addressed when its sentence occurs in the
  body (server rule); clicking a chip inserts the sentence and hides the chip (client).
- **D9 Sinking funds reuse `savings_goals`** through `savings.list_goals(year)` (pooled
  balance, `required_monthly`, `projected_completion`, `on_track`). No new fields.
- **D10 Process.** Docs PR (ADR-0021 + glossary + this plan) → vertical slices as
  ready-for-agent sub-issues of #140, one PR each → closeout PR.

## Product Contract

### Summary

Nav: `Planning ▾` after Reports with Month, Notebook, Planner. Router `app/routers/planning.py`
(no prefix: pages under `/planning/…`, the API under `/api/planning/…`), registered after
`reports` in `ROUTER_MODULES`.

| Route | Behaviour |
|---|---|
| `GET /planning`, `/planning/month` | 303 → `/planning/month/{budgets.current_month()}` |
| `GET /planning/month/{ym}` | `planning_month.html`: five stat tiles (income, spend vs budget, net, net savings rate, Net worth + delta), Budget-vs-Actual with status pills, Income expected-vs-received per Recurring series, sticky journal panel (frozen strip, textarea, Save, Refreeze), Prompt chips, ← → month links |
| `GET /planning/notebook` | 303 → current month |
| `GET /planning/notebook/{period}` | `planning_notebook.html`: rail (last 24 months with net bar and ✎ when written, year links), the entry as a document (title, byline, Figure blocks, rendered prose), "Not yet addressed" chips, prev/next; `?edit=1` = textarea + live preview, Ctrl-S |
| `GET /planning/planner` | 303 → current year |
| `GET /planning/planner/{year}` | `planning_planner.html`: 12-cell strip (income/spend bars, net; future months dashed "expected"), Checking forecast chart (ECharts) with low-point callout and events table, Expected income per source (expected / received YTD / remaining), Sinking funds, journal drawer for the current month |
| `POST /api/planning/entry/{period}` `{body}` | upsert body; first save freezes figures → `{ok, entry}` |
| `POST /api/planning/entry/{period}/refreeze` | recompute `figures` and `frozen_at` |
| `POST /api/planning/entry/{period}/delete` | `deletions.log("journal_entries", [row])`, then delete (ADR-0005) |
| `GET /api/planning/forecast?days=90` | forecast JSON |

Bad period → 404 page / 400 JSON. Every derived number carries "· estimated from ledger".

### Data

Migration `0015_journal_entries.sql`:

```sql
CREATE TABLE journal_entries (
    id         TEXT PRIMARY KEY,
    period     TEXT NOT NULL UNIQUE,   -- "YYYY-MM" (month) or "YYYY" (year review)
    body       TEXT NOT NULL DEFAULT '',
    figures    TEXT,                   -- JSON frozen at first save / refreeze
    frozen_at  TEXT,
    created_at TEXT,
    edited_at  TEXT
);
```

`app/store/journal_entries.py`: `period`, `body`, `figures` (json), `frozen_at` (datetime);
`for_period(period)`, `periods_written() -> set[str]`. Data-health section "Planning
journal"; `tests/test_store.py` `LATEST = 15` + table; `docs/schema.mmd` regenerated.

Frozen `figures` keys: `period, income, expense, net, savings_rate, net_worth,
net_worth_delta, net_worth_as_of, budget_version, budget_total, actual_total, misses
[{group, budget, actual, over}] (top 4), months12[], net12[], frozen_at`. Year periods omit
`misses` and `budget_*`; `net12` is the year's months.

`app/networth.py`: `canon_class`, `month_rows`, `CLASS_ORDER`, `summarize(rows) -> {assets,
liabilities, net_worth}`, `async net_worth_at(ym) -> {net_worth, assets, liabilities, as_of}
| None`, `async net_worth_delta(ym) -> {value, prev, delta, as_of}`.

`app/recurring.py`: `normalize_merchant(desc)` (`pending.normalize`, drop `web id: …` tails,
leading `paypal purchase` / `paypal inst xfer`, digit tokens and x-masks). `CADENCES` by median
gap in days: weekly 5–9, biweekly 12–16, monthly 26–35, quarterly 80–100, semiyearly 170–195,
yearly 350–380. `detect(rows, *, today, lookback_days=730, min_count=3)` → `[{key, label,
category, cadence, period_days, amount (median |amount| of last 3), last_date, next_date
(advanced to ≥ today), count, expected_count, confidence, per_month}]`; no cadence →
`cadence="irregular"`, `per_month=None`; ended series (last date older than two periods)
dropped; quarterly and slower need only two points. Loaders `income_sources(today)` (Type
Income, not pending, by Category) and `bills(today)` (Type Expense, amount < 0, category
Timing in Monthly / Weekly / Quarterly / Semi Yearly / Yearly, by normalised merchant).

`app/planning.py`: `month_label`, `prev_month`, `next_month`, `is_period`;
`budget_for_month(ym)` (D4); `month_facts(ym, today=None)` → `{month, label, days,
is_current, income, expense, net, savings_rate, target_rate, avg_net_12, budget {id,
versionName, status, rows, budget_total, actual_total} | None, income_sources [{source,
cadence, expected, received, next}], net_worth, series12, uncategorized, estimates[]}`;
`figures_from_facts`; `prompts(facts, prior_reports)` — unbudgeted group (|actual| ≥ 25),
over budget ≥ 15 %, over budget three months running, budget line with no activity, net-worth
change, N uncategorized; `addressed(prompts, body)`; `year_facts(year, today)` → months
(actual | partial | expected), expected income per source (annualised vs received YTD), funds
via `savings.list_goals(year)`; `forecast(today, days=90)` → `{start_balance, accounts,
daily_variable, series[{date, balance}], events[{date, label, amount, balance_after}], low,
end_balance, estimated: true}`; journal ops `get_entry`, `save_entry`, `refreeze`,
`delete_entry`; `notebook_blocks(body, figures)` (D7).

Templates follow `budget_report.html` (extend base, `.page-head`, data via a nonced
`window.PLANNING = {{ … | tojson }}`, one JS file per page with `css_v`). CSS additions:
`.frozen`, `.chips` / `.chip`, `.pill.ok/.over/.warn/.none`, `table.t`, the three page grids,
the drawer; tiles reuse `.summary-cards .card.stat`.

## Slices (as built, 2026-10-05)

Vertical slices, one PR each, sub-issues of #140, all merged the same day:

1. **Docs first: ADR-0021 and glossary** (#141) — the ADR, eight glossary terms, this plan — PR #152.
2. **Net worth has one owner** (#142) — `app/networth.py` (`canon_class`, `month_rows`,
   `summarize`, `net_worth_at` with the fallback month, `net_worth_delta`); the balance sheet
   imports it, figures unchanged; `tests/test_networth.py` — PR #151.
3. **Month page with real figures** (#143) — nav, router, redirects, five tiles,
   Budget-vs-Actual with the D4 pick rule and pills, 404 on a bad month; `app/planning.py`
   (`month_facts`, `budget_for_month`, `budget_report`); `tests/test_planning.py`,
   `tests/test_planning_pages.py` — PR #153.
4. **Journal entry on the Month page** (#144) — migration `0015_journal_entries.sql`, store,
   data-health section, schema doc, `figures_for` / `save_entry` / `refreeze` /
   `delete_entry` (audited), the sticky panel, `planning-entry.js` — PR #154.
5. **Prompts from the data** (#145) — `prompts`, `addressed`, `month_prompts`, the chips
   card — PR #156 (stacked on #155).
6. **Recurring series from the ledger** (#146) — `app/recurring.py`, `income_table`, the
   Income card; `tests/test_recurring.py`, `tests/test_planning_income.py` — PR #155.
7. **Notebook page** (#147) — `notebook_blocks`, `notebook_rail`, `notebook_view`,
   `planning_notebook.html`, `planning-notebook.js`; `tests/test_planning_notebook.py` — PR #158.
8. **Planner page: year strip, expected income, sinking funds** (#148) — `year_facts`,
   `expected_month`, `variable_daily_spend`, `planning_planner.html`, the drawer;
   `tests/test_planning_planner.py` — PR #157.
9. **90-day checking forecast** (#149) — `checking_accounts`, `project`, `forecast`,
   `GET /api/planning/forecast`, `planning-forecast.js`; `tests/test_planning_forecast.py` — PR #159.
10. **Closeout** (#150) — README, CHANGELOG, glossary, this plan — this PR.

Full suite after slice 9: 763 passed, 1 skipped; `schema_doc.py --check` green.

Deviations from the contract above, each recorded in its PR:

- The entry API lives under `/api/planning/…`, not `/planning/api/…`, so a CSRF rejection
  answers in JSON like every other `/api/` route (slice 4).
- A zero-amount budget line with no spend shows "no activity", not the engine's "On Target"
  (slice 3); unbudgeted spend counts among the frozen `misses` (slice 4).
- The "no activity" prompt fires for finished months only — a month that has just begun
  flooded the panel with every untouched line (slice 5).
- A Recurring series carries `first_date`, and a month before the series began expects
  nothing; `income_sources` on `month_facts` is `{rows, expected_total, received_total}`,
  and a series with nothing expected and nothing received in the month is left out (slice 6).
- `notebook_view` assembles the Notebook's whole context; rail bars and the sparkline are
  inline SVG (the CSP allows no `style` attributes); a chip in view mode saves the sentence
  through the entry API and reopens Write mode; the rail lists every ledger year (slice 7).
- `planning-month.js` became `planning-entry.js`, shared by the Month panel and the Planner
  drawer through the same element ids; bar widths are `data-w` attributes the page script
  applies (slice 8).
- `bills()` keeps only series whose last three amounts spread by ≤ 25 % (`detect()` reports
  `spread` and `stable`): on the live ledger the Weekly-timed gas stations and coffee shops had
  qualified as bills, 211 events in 90 days; 75 after, and the variable rate carries the rest
  (slice 9).

What the live ledger showed: one checking account; no periodic Income category (the large
income is one-off, the rest irregular), so expected income reads $0 and the forecast only
descends. That is the honest estimate; the first follow-up below is what would change it.

## Verification

- `./.venv/bin/python -m pytest -q` green after each slice; `./.venv/bin/python
  scripts/schema_doc.py --check` after slice 4.
- Manual check on a **copy** of `data/`, never the live directory: a scratch launcher that
  points `DATA_DIR` at the copy, sets `app.state.auth_disabled` and `csrf_disabled` the way
  `tests/conftest.py` does, and serves on 8099. Open `/planning/month/{current month}` (the
  budget pick rule against months that hold both a saved and a draft version),
  `/planning/notebook/{month}`, `/planning/planner/{year}` (the checking accounts as the
  starting balance; a merchant's PayPal variants folded into one bill). Live-data command
  output stays at counts.
- Screenshots per slice (`chromium --headless=new --screenshot --window-size=1400,1000`) on
  the PR; the closeout set (Month, Notebook, Notebook Write mode, Planner) is on PR #160.
- Production rebuild after merge only when asked, through the production compose project.

## Follow-ups (out of scope)

- An Income Sources registry (typed expected amount and cadence, overriding detection) —
  the live ledger has no periodic Income category, so this is what makes expected income and
  the forecast useful.
- Per-fund balances or a monthly contribution on `savings_goals`; fund draws in the forecast.
- Yearly budgets; a stored Themes list for the year.
- Forecast per checking account and a configurable account set.
- Delete the prototype once a layout wins and record the verdict here. Candidates noticed
  while building: the Notebook rail lists every ledger year (long); a month with a budget and
  nothing over it still shows an empty "Biggest misses" block.
