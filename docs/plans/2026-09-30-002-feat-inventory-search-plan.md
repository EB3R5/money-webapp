---
title: Inventory Search - Plan
type: feat
date: 2026-09-30
topic: inventory-search
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Inventory Search - Plan

## Goal Capsule

- **Objective:** Find an Item by typing. A search box on the Inventory card board filters
  the cards as you type, and the Column view filters its tree the same way. The same
  feature lands on future-purchases' two boards from the shared CardCollection lineage.
- **Product authority:** This document. Decisions confirmed in dialogue 2026-09-30.
- **Stop conditions:** none open.

## Key Decisions

- **D1 Instant, client-side on the board.** Every row is already on the page, so the box
  hides non-matching cards and empty sections, re-totals what is shown, and keeps the term in
  the URL as `?q=` (replaceState; the server pre-fills the box on load). No round trip.
- **D2 Scope (money):** the `/inventory` card board and the `/inventory/columns` view. The
  column view re-fetches `/api/inventory/tree?q=` (150 ms debounce) so counts and values roll
  up server-side from the same rule; a sequence guard drops stale replies and the open path
  is re-selected where it still exists.
- **D3 One rule.** `app/search.py`: up to six words, every word must be a case-insensitive
  substring of some searched field. The clip picker, the tree, and the JS mirror in
  `card-editor.js` all use it. Searched fields (`inventory_item.SEARCH_FIELDS`): every
  descriptive text field plus Item_ID, never Link (URL noise; Source names the retailer),
  never numbers or dates. The picker's fields widen as a consequence.
- **D4 A CardCollection capability.** `search_fields` config; the box, the count/grand
  hooks, the section-total hook, and the no-match line render only when set. Cards and
  sections hide through the `hidden` attribute plus one CSS rule (author `display` would
  otherwise win). No inline styles or handlers (CSP).
- **D5 Reloads and keys.** Update/delete reloads keep `?q=`; the create reload drops it so
  the new card is visible. `/` focuses the box, Escape in the box clears it.

## Slices (as built)

1. `feat(search)`: `app/search.py`, `SEARCH_FIELDS`, clip picker refactor, tree `?q=`,
   `tests/test_search.py`, tree tests.
2. `feat(inventory)`: `CardCollection.search_fields`, template hooks and input, CSS,
   `card-editor.js` search block, column page input and `inventory-columns.js` re-fetch.
3. `docs`: changelog, glossary, this plan.

## Follow-ups (out of scope)

- Search on the Accounts board (one config line when wanted).
- Highlighting matches inside cards.
