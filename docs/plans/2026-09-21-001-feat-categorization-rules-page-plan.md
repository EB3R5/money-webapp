---
title: Categorization Rules Page - Plan
type: feat
date: 2026-09-21
topic: categorization-rules-page
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Categorization Rules Page - Plan

## Goal Capsule

- **Objective:** Separate the Rule engine from the ML model everywhere they meet the user,
  and give Rules a real editor: a Categorization page with a Rules tab (ordered, enable/
  disable, match preview, test form) and an ML model tab (info, retrain); a Ledger whose
  toolbar runs Rule apply and ML suggest separately and whose side panel shows the Rule hit
  and the ML picks by source without writing on a row click.
- **Product authority:** This document. Decisions confirmed in dialogue 2026-09-21: one new
  page with two tabs; separate Ledger buttons and endpoints; explicit `order` on Rules
  backfilled from natural order, move up/down; editor extras are preview counts, "Test a
  transaction", enable/disable; no per-rule "apply now"; row click no longer writes.
- **Stop conditions:** none open.

## Product Contract

### Summary

`/categorization` has two tabs. **Rules** is an editable grid over `autocat` in first-match-
wins order: `#`, enabled, move ▲▼, the five conditions, Category, Issues, and the preview
counts Matches / Wins / Uncategorized (click a count for sample rows); an add modal, delete-
selected, "Refresh counts", and a side panel with "Test a transaction". **ML model** shows the
current pointer row (trained at, rows, categories, scikit-learn version, SHA-256, file) and a
retrain form with optional date and account filters.

The Ledger toolbar has "Apply rules" and "ML suggest" (plus "Manage rules"); the panel shows a
Rule section (one "Apply rule #N → Category" chip) and an ML section (confidence chips).

### Key Decisions

- **Two engines, one meeting point.** `app/autocat.py` is the Rule engine and the Rule
  editor's operations; `app/ml_model.py` only proposes. `app/categorization.py` is the one
  module where they touch Transactions (Category write with cascade, Rule apply, ML
  suggestion, read-only suggest, test), mirroring the credit module/router pairing.
- **Explicit order.** Schema 0002 adds `order` and `enabled`; rows that predate the columns
  are numbered once from insertion order, so sheet semantics carry over.
- **Preview in Python.** One scan over a narrow projection; precedence is the engine's own
  `_matches`, never a database-side pattern. Disabled Rules report matches but never wins.
- **Unknown Category is a warning.** Existing Rules keep firing; add and update reject an
  unknown Category going forward.
- **Nothing writes on a row click.** Every write is an explicit chip click or toolbar action.
- **Removed:** `POST /api/transactions/autocat-batch`, the Ledger "Retrain model" button.

## Surfaces

- `app/autocat.py` — engine (`ensure_order`, `sorted_docs`, `load_rules`, `_compile`,
  `_compile_any`, `_txn_fields`, `_matches`, `match`) + operations (`list_rules`, `add_rule`,
  `update_rule`, `delete_rule`, `move_rule`, `preview`, `test_rule`).
- `app/categorization.py` — `apply_category`, `derived_for`, `apply_rules`, `suggest_batch`,
  `suggest_for`, `test_transaction`.
- `app/ml_model.py` — `model_info` (plus the store-backed storage from the Ledger port).
- `app/routers/categorization.py` — `/categorization`, `/api/rules/*`, `/api/ml/*`,
  `/api/transactions/{id}/suggest`.
- `app/routers/ledger.py` — Category endpoint only; imports the cascade from categorization.
- `app/templates/categorization.html`, `app/static/js/categorization.js`,
  `app/templates/ledger.html`, `app/static/js/ledger.js`, `app/static/css/app.css`.
- `app/store/autocat.py` (`in_order`, `unordered`, `max_order`),
  `app/store/transactions.py` (`blank`, `for_matching`), `app/store/schema/0002_*.sql`.
- Docs: `CONTEXT.md` (Rule, Rule engine, ML model, ML suggestion, Rule apply),
  `docs/schema.mmd`, `README.md`, `CHANGELOG.md`.

## Delivery

Landed on the `sqlite` branch as one PR per slice: #43 (order + enabled), #44 (Ledger
split), #45 (Rules tab), #46 (preview + test form), and the ML model tab. Tests:
`tests/test_autocat.py` (engine), `tests/test_rules_editor.py` (operations, page,
endpoints, preview, test form), `tests/test_categorization.py` (where the engines meet the
Ledger), `tests/test_ml_model.py` (`model_info`, storage, retrain).
