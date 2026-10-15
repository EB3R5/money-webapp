---
title: Ledger edits survive the SimpleFIN sync - Plan
type: fix
date: 2026-10-03
topic: ledger-edits-survive-sync
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Ledger edits survive the SimpleFIN sync - Plan

## Goal Capsule

- **Objective:** A cell edited on the Ledger stays edited. Diagnosis: the edit path was sound
  (`POST /api/transactions/update` → `Grid.update_field` → `transactions.update`, committed
  per request); the scheduled SimpleFIN run re-read its ~5-day window every 6 hours and wrote
  the bank's values back over any provider field that differed — exactly the five fields the
  Ledger lets a person edit. Category survived because it is app-owned.
- **Product authority:** This document and ADR-0019. Decided in dialogue 2026-10-03: a hand
  edit always wins, per field.
- **Stop conditions:** none open.

## Key Decisions

- **D1 Per-field provider snapshot.** `transactions.provider_values` (API `_provider`, JSON,
  migration 0013): the feed's last-applied value for `SNAPSHOT_FIELDS` (Date, posted_at,
  Description, Full Description, Amount, Account, Institution, pending, Metadata), normalized
  by `provider_norm` and compared by `provider_same` (`app/store/transactions.py`). No
  backfill: a legacy row keeps its values and starts its snapshot on its next run.
- **D2 The rule** (`_upsert_transaction`, `app/simplefin/sync.py`): per field, bank ≠ snapshot
  and row = snapshot → write the bank's value; row ≠ snapshot → keep the row's value,
  whatever the bank says. Snapshot and `last_seen_at` refreshed every run; `Month` derived
  from the effective Date; `txns_updated` counts only real value changes, `txns_hand_kept`
  counts rows where a bank change was skipped.
- **D3 Hand edit wins always** (not "until the bank changes that field"): a pending row
  posting with a new date/description must not undo a date corrected for a report.
- **D4 Pending twins** (`app/simplefin/pending.py`): matched on the bank's Amount and
  description (`provider_value`), with `pending_twins` no longer filtering on the stored
  amount; the person's hand edits on the five editable fields ride onto the posted row.
- **D5 Client** (`ledger.js`, `grid-factory.js`): the Amount parser accepts `$`, `,`, `(…)`
  and refuses anything non-numeric, keeping the old value and saying why in the toolbar
  status; `onSaved(ok, e, d)` carries the server reply and a failed save is shown there.

## Slices (as built, 2026-10-03)

1. Store + migration 0013, helpers, `pending_twins` signature, schema doc, `LATEST = 13`.
2. Sync rule, `txns_hand_kept`, docstring.
3. Pending matching and carry.
4. Client guard and status.
5. Tests: `tests/test_simplefin_sync.py` (+6), `tests/test_pending.py` (+1),
   `tests/test_ledger.py` (+1 HTTP round trip). Full suite 681 passed.
6. Docs: ADR-0019, ADR-0014 note, glossary (Hand edit; Feed and Pending reconciliation
   amended), CHANGELOG, this plan.

## Follow-ups (out of scope)

- ~~`Grid.update_field` does not recompute `Month` when Date is edited~~ — done 2026-10-04:
  `Grid.derive` (`derive_month`) on the Ledger grid, for inline updates and added rows.
- A feed row deleted and reinserted (an account ignored then re-linked) loses its edits.
