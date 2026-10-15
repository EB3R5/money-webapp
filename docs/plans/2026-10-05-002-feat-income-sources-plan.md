---
title: Income sources registry - Plan
type: feat
date: 2026-10-05
topic: income-sources
artifact_contract: ce-unified-plan/v1
artifact_readiness: ready
product_contract_source: dialogue
execution: code
---

# Income sources registry - Plan

## Goal Capsule

- **Objective:** Typed expected income for the Planning section. The live ledger has no
  periodic Income category, so expected income reads $0 and the Checking forecast only
  descends (ADR-0021 follow-up). An **Income source** is a row the person types — name, the
  Income category it lands in, a cadence, an amount, the next expected date — and the
  Planning pages read the active sources first and the detected Recurring series whose
  category no source claims after them.
- **Product authority:** #161 (#161) and
  ADR-0022; decisions chosen in dialogue on 2026-10-05.
- **Stop conditions:** none open.

## Key Decisions

- **D1 Where.** An Income page under Planning ▾ (`/planning/income`): the sources table with
  add, edit, deactivate and delete, the form whose category picker lists the Income
  categories, and the detected series below with "Use this" prefilling the form.
- **D2 Linking** (ADR-0022). Each source links to an Income category; received is that
  category's actual income in the month or year. A typed source replaces the detected series
  for the same category; unmatched detected series still show, labelled detected. Inactive
  sources are ignored everywhere and kept.
- **D3 Cadences.** weekly, biweekly, semimonthly (the anchor's day and the day fifteen later
  each month, clamped), monthly, quarterly, yearly (same day of the month, clamped), irregular.
  The anchor date is the next occurrence when written; the app steps forward from it.
- **D4 One shape.** `income_sources.as_series()` yields the detector's series shape plus
  `origin`; `due_dates()` and `occurrences_in_month()` dispatch on the origin, so the
  consumers (`income_table`, `year_facts`, `forecast`) read one merged list.

## Product Contract

### Summary

| Route | Behaviour |
|---|---|
| `GET /planning/income` | `planning_income.html`: sources table (name, category, cadence, amount, per month, next, active; Edit / Deactivate / Delete), the add/edit form, the detected series with "Use this" |
| `POST /api/planning/income` | add: `{name, category?, cadence, amount, anchor_date?, notes?, active?}` → `{ok, id}` |
| `POST /api/planning/income/update` | dirty-diff edit by `id`; `active` toggles |
| `POST /api/planning/income/delete` | audited delete (ADR-0005) |

Nav: `Income` under Planning ▾. Validation: name required; amount positive; cadence in the
set; anchor a date; category, when given, an existing Category.

### Data

Migration `0016_income_sources.sql`: `income_sources(id, name NOT NULL, category, cadence NOT
NULL, amount REAL NOT NULL, anchor_date, active INTEGER DEFAULT 1, notes, created_at,
edited_at)`, index on category. Store `app/store/income_sources.py` (`active()`); data-health
section "Income sources"; `LATEST = 16`.

`app/income_sources.py`: `add_months`, `occurrences(cadence, anchor)`, `next_date`,
`registry_due_dates`, `registry_occurrences_in_month`, `as_series(source, today)`,
`due_dates(series, start, end)`, `occurrences_in_month(series, ym)`, `merged_sources(today)`,
`income_categories()`, `list_sources`, `add_source`, `update_source`, `delete_source`.

## Slices

1. **Table, domain, and the Income page** (#162) — ADR-0022, glossary (Income source,
   Income page), migration, store, `app/income_sources.py`, routes, template,
   `planning-income.js`, `tests/test_income_sources.py`.
2. **Planning pages read the merged sources** (#163) — `planning.income_table`,
   `year_facts`, `forecast` and their helpers switch from `recurring.income_sources` to
   `income_sources.merged_sources` and dispatch stepping through `income_sources.due_dates`
   / `occurrences_in_month`; rows carry `origin` and the pages mark detected ones. Blocked by #162.

## Verification

- `./.venv/bin/python -m pytest -q` green per slice; `scripts/schema_doc.py --check` after slice 1.
- On a copy of the live data: add a semimonthly paycheck on the Income page, then see it on
  the Month page's income table, the Planner's expected income and months, and the forecast's
  events, with the detected rows still present for unclaimed categories.

## Follow-ups (out of scope)

- A source that ends (an end date), and raises on a schedule.
- Matching received by amount and date when a source has no category.
