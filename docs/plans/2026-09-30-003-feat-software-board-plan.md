---
title: Software Board - Plan
type: feat
date: 2026-09-30
topic: software-board
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Software Board - Plan

## Goal Capsule

- **Objective:** Track the software you have — installed, subscribed, in use — on a card
  board of its own under the Inventory ▾ menu, with an import endpoint for an exporter's
  run, a clipper for repo / package / app store / pricing pages, and one page listing every
  clipper. Ported from future-purchases' Software board (merged there the same day) onto
  the SQLite store; that app keeps prospective software and upgrade paths.
- **Product authority:** This document and ADR-0017. Decisions confirmed in dialogue
  2026-09-30 (research note: `~/Downloads/software-inventory-tracking.md`, 2026-09-18).
- **Stop conditions:** none open.

## Key Decisions

- **D1 Own table + own board**, slug `/software` (not `/inventory/software`: the nav's
  active-link script prefix-matches). Nav entry inside Inventory ▾.
- **D2 Engine transplant, CSP-safe.** `group_options`, `default_group`, `entry_sort`,
  `link_field`, `default_status` from future-purchases' engine. No inline handlers: the
  status filter's `onchange` moves into `card-editor.js` (fixing Accounts under the CSP),
  the ↗ link has no `onclick`; cards become `<div role="button" tabindex="0">`.
- **D3 Import stays HTTP** (`POST /api/software/import`), logic in `app/software_import.py`;
  the board's import strip posts a run file from the browser (CSRF, no token bypass).
- **D4 Clipper in this app's shape** (prepare → tick → apply through the board's routes),
  registry JSON server-side, OG + SoftwareApplication harvested client-side, no
  BeautifulSoup. Registry-owned facts go through `POST /api/software/{id}/facts`.
- **D5 One popup for all clippers** (`clip.html` + `clip.js`, `window.CLIP`), with a
  route-owned CSP allowing `https:` images. **One Clippers page** (`/clippers`); the old
  setup URL redirects.
- **D6 Categories** are free text with a datalist of what is on the board; duplicate
  `Source_Key` is refused at the app layer on top of a partial unique index.

## Slices (as built)

1. `feat(store)`: `0011_software.sql`, `store/software.py`, health section, schema doc.
2. `feat(software)`: `software_item.py`, `software_clip.py` (pure), `GITHUB_TOKEN`.
3. `feat(card-collection)`: the five engine options, template, JS, CSS.
4. `feat(software)`: board adapter, import strip, `software.js`, nav, `/facts`.
5. `feat(software)`: import endpoint.
6. `feat(software)`: clipper — bookmarklet, prepare, shared popup, popup CSP.
7. `feat(clippers)`: the Clippers page and redirect.
8. `docs`: ADR-0017, glossary, changelog, README, deployment notes, this plan.

## Follow-ups (out of scope)

- "⟳ Refresh from source" modal action (`fetch_by_source_key` → `/facts`).
- `scripts/import_software.py` (apply a run file in-process) and the Mac collectors; copying
  future-purchases' `scripts/export_installed.py`.
- `Merchant_Match` evaluated against `transactions.Description` (the ledger link).
- future-purchases: narrow its Software board to prospective software / upgrade paths and
  point its exporter here.
- `scripts/db_census.py` counts inventory photos only.
