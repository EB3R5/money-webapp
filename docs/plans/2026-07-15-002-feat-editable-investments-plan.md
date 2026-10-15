---
title: Editable Investments Page - Plan
type: feat
date: 2026-07-15
topic: editable-investments
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Editable Investments Page - Plan

## Goal Capsule

- **Objective:** Make Investments rows editable in place — position facts only — so the page linked cards point at ("Manage on Investments") can actually manage the portfolio.
- **Product authority:** This document; decisions confirmed in dialogue 2026-07-15.
- **Product Contract preservation:** changed R3 (Avg Cost is the visible readback for a Purchase Price edit — user-directed: Avg Cost = Purchase Price ÷ Shares in this dataset) and R5 (cash rows show Shares + Brokerage only) — both confirmed in the 2026-07-15 review walkthrough.
- **Open blockers:** None.

---

## Product Contract

### Summary

Clicking a holding on the Investments page opens the app's standard editor modal with the row's position facts — Shares, Purchase Price, Brokerage. Saving updates the holding; the row's value recomputes from the edited shares at the last known price, and the linked account card and next portfolio sync pick the change up through the existing derive-at-read and sync paths with no extra wiring.

### Requirements

- R1. Each holding row on the Investments page opens an editor modal on click, following the app's existing card-editor pattern (dirty-diff save).
- R2. Editable fields are exactly Shares, Purchase Price, and Brokerage; all other columns are display-only in the modal.
- R3. Saving an edited Shares value recomputes the holding's value at its last known price, so the page, the linked card, and the next sync all reflect the edit without a price refresh. An edited Purchase Price is visible through the Avg Cost column, which recomputes as Purchase Price ÷ Shares on save.
- R4. Ticker and live-price fields are not editable; the modal treats them as identity/display.
- R5. Cash rows open the same modal showing Shares and Brokerage only (no Purchase Price — cash has no cost basis distinct from value); editing shares is how a cash balance adjusts.

### Acceptance Examples

- AE1. **Covers R3.** Given a holding of 10 shares last priced at $250 — editing shares to 12 shows a value of $3,000 on the page and on its linked account card, before any price refresh runs.

### Scope Boundaries

- No adding or removing holdings on this page — new stocks enter via Add account; removal is archive.
- No ticker renames — wrong ticker is corrected by archive + recreate.
- No edits to Current Price / refresh-owned fields; Refresh prices stays the only price writer.
- Closed (archived) holdings stay hidden; no editing of archived rows.

---

## Planning Contract

### Key Technical Decisions

- KTD-1. **Reuse `makeCardEditor`, not a new editor and not a page conversion.** The Investments page stays a table; `app/static/js/card-editor.js` gains two small options — a row-selector (default stays `.acct-card`, so Accounts/Inventory are untouched) and a reload-on-successful-update flag (the editor's update path repaints card elements that don't exist in a table row, and the server's recomputed values never reach the client; a reload matches the page's existing Refresh/Sync feedback). The template embeds the standard modal markup; the page passes its holdings as one pseudo-section in the editor's existing data shape. Cash rows hide the Purchase Price field (R5).
- KTD-2. **One bespoke update endpoint, source-typed writes.** A holding-update route in the investments router whitelists exactly Shares, Purchase Price, and Brokerage (stored as the holding's `Account` field), coerces numbers (garbage → 400, matching the card pages' behavior), and writes back in the collection's source-typed string formats (`Shares` as a plain number string, `Purchase Price` in the `money()` format). Unknown holding → 404; `_closed` holding → 400. Use a literal-prefixed path (e.g. `/api/investments/holding/{id}`) so the param route cannot shadow the existing refresh/sync POSTs — the registration-order hazard `app/card_collection.py` already documents.
- KTD-3. **Server-side recompute on save.** After a Shares or Purchase Price edit, the endpoint recomputes `Current Value`, `Return`, `Delta`, and `Avg Cost` (Purchase Price ÷ shares — the table's visible readback for a cost-basis edit). The price used is an explicit fallback chain: last known `Current Price`; else `Purchase Price` ÷ **pre-edit** shares; else existing `Current Value` ÷ pre-edit shares (covers cash at ~$1/share); else reject 400 — never derive the price from post-edit shares, which would neutralize the edit. Mirrors the math `refresh_prices` already applies; extracting a small shared helper in `app/investments.py` is preferred over duplicating it.
- KTD-4. **No new wiring for propagation.** The linked card picks the new value up through the existing derive-at-read overlay (`app/routers/accounts.py`), and the next sync reads `Current Value` as always — R3 is satisfied by construction; tests assert it rather than code enabling it.

### Assumptions

- A1. `portfolio_rows` gains the holding's `_id` so rows can be click-targets; exposing the raw id to the template is acceptable (same as the card pages). Each row entry also carries the three editable values keyed by the modal's field names — `Shares` and `Purchase Price` as their stored source strings, `Brokerage` mapped from the holding's `Account` field — so the modal prefills (the read-side mirror of KTD-2's write mapping).

---

## Implementation Units

### U1. Holding update endpoint with recompute

- **Goal:** POST-editable position facts on a holding, with value/return recomputed server-side.
- **Requirements:** R2, R3, R4, R5.
- **Dependencies:** none.
- **Files:** `app/investments.py` (recompute helper), `app/routers/investments.py` (update route), `tests/test_investments.py`.
- **Approach:** KTD-2, KTD-3. Whitelist-coerce-store; recompute `Current Value`/`Return`/`Delta` from edited shares at last known price; keep all writes source-typed strings.
- **Patterns to follow:** `CardCollection.update`'s whitelist + ValueError→400 shape (`app/card_collection.py`); `refresh_prices`' value math and `money()` formatting (`app/investments.py`).
- **Test scenarios:** edit shares 10→12 with `Current Price` $250 → `Current Value` "$3,000.00", `Return` reflects new value − cost; edit Purchase Price → Return/Delta and `Avg Cost` (= purchase ÷ shares) recompute, value unchanged; edit Brokerage → holding `Account` updated, money fields untouched; never-refreshed holding (no `Current Price`) → value derives from purchase ÷ pre-edit shares; cash row (no `Current Price`, no `Purchase Price`) shares edit → value derives from existing value ÷ pre-edit shares, never $0; garbage shares ("abc") → 400; zero/negative shares → 400; unknown id → 404; `_closed` holding → 400; field outside the whitelist (e.g. `Asset`, `Current Price`) in the payload is ignored or rejected — never written.
- **Verification:** pytest green; a curl-style POST against the test client changes exactly the intended fields.

### U2. Clickable rows + editor modal on the Investments page

- **Goal:** Row click opens the standard editor modal; dirty-diff save hits U1's endpoint; page reloads with fresh numbers.
- **Requirements:** R1, R2, R5.
- **Dependencies:** U1.
- **Files:** `app/templates/investments.html` (row `data-id`s, modal markup, editor wiring), `app/investments.py` (`portfolio_rows` carries the holding id — A1), `app/static/js/card-editor.js` (optional row-selector option), `tests/test_investments.py` (template assertions).
- **Approach:** KTD-1. Rows render `data-id` and are keyboard-operable like the card pages' buttons (tabindex, Enter/Space activation, hover/focus cue); the page initializes `makeCardEditor` with the three-field config, its endpoint, the reload-on-update flag, and the pseudo-section data (A1's field-name-keyed values); the existing Refresh/Sync inline script stays as-is. Cash rows carry ids like any other row but hide the Purchase Price field (R5).
- **Test scenarios:** page HTML carries `data-id` per holding row and the modal markup with exactly the three editable inputs; closed holdings still absent from the page (regression); no `data-id` on the totals row.
- **Verification:** pytest green; in the running app a row click opens the modal, save updates the row after reload.

### U3. Acceptance and propagation coverage

- **Goal:** AE1 proven end-to-end; the derive-at-read and sync integrations asserted.
- **Requirements:** R3; AE1.
- **Dependencies:** U1, U2.
- **Files:** `tests/test_account_entry.py` (linked-card propagation), `tests/test_investments.py` (sync uses edited value).
- **Test scenarios:** Covers AE1 — fan-out-created stock (10 shares, refreshed to $250) edited to 12 shares → Investments page and Accounts page both show $3,000 with no refresh; a sync after the edit appends a snapshot with the recomputed value; legacy (unlinked) holding edit behaves identically on the Investments page — note a legacy holding may have a name-matched Accounts card that `refresh_prices` keeps in sync; that card lags an edit until the next refresh, accepted under R9's two-regimes rule.
- **Verification:** full suite green.

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Unit + integration tests | `./.venv/bin/python -m pytest -q` | every unit; full suite green including pre-existing investments/accounts tests |
| Live smoke | edit a real holding's shares on the running app once merged; confirm the row, its card, and the next sync agree | post-merge, user-driven |

## Definition of Done

- U1–U3 landed; full pytest suite green; AE1 demonstrated by a named test.
- Editing is limited to the three position facts; price fields provably not writable through the endpoint.
- Accounts/Inventory card pages unaffected (selector default preserved).
- No dead experiments left in the diff.

---

## Sources

- The page renders a read-only table from the portfolio collection (`app/routers/investments.py`, `app/investments.py` `portfolio_rows` — no id in rows today); the editor pattern to reuse is `app/card_collection.py` + `app/static/js/card-editor.js` (selector currently hardcoded to `.acct-card`); linked-card value display derives at render (`app/routers/accounts.py`), so holding edits surface there automatically. All verified in-session 2026-07-15 while shipping dynamic-account-entry (PR #7).
