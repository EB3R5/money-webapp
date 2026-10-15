---
title: Kits - Plan
type: feat
date: 2026-10-03
topic: kits
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Kits - Plan

## Goal Capsule

- **Objective:** A **Kit** is a named set of Items and Software that serve one purpose — the
  home gym, the sous-vide setup, the backup chain — with a short Description, a Markdown
  "How to use", its own photos and Documents, shown with the pictures of everything in it
  and edited through a transfer list. Kits get a page of their own (`/kits`, Inventory ▾),
  and every Item and Software shows the Kits it belongs to.
- **Product authority:** This document and ADR-0018. Decisions made on the wayfinder map
  Kits — functional groups of Items and Software (#103)
  on 2026-10-03; the design is prototype Variant B
  (Kit page layout (#104)).
- **Stop conditions:** none open.

## Key Decisions

- **D1 Vocabulary.** The entity is a **Kit**, never "group" (taken by the ledger Category's
  Group field, the inventory-category Group and the card editor's Group-by). Glossary: Kit,
  Kit member (`CONTEXT.md`).
- **D2 A Kit is a view over owned things** (ADR-0018). It owns no Item, has no cost of its
  own and never rolls up into the balance sheet, the Inventory Overview or any report. Its
  page shows the sum of its members' Value and the monthly cost of its *active* software,
  computed at read time.
- **D3 Schema** (ticket (#105)): migration
  `0012_kits.sql` with `kits(id, name NOT NULL, description, how_to, images, created_at,
  edited_at)` and `kit_members(id, kit_id REFERENCES kits(id) ON DELETE CASCADE,
  member_table, member_id, position, …)`, `UNIQUE(kit_id, member_table, member_id)`, an
  index on `(member_table, member_id)`. One polymorphic member pair (as `documents`), a real
  foreign key on the kit side only, `position` = order added. **Identity is the row id**; no
  `KIT-###`. Member keys on the wire are `inventory:<row id>` / `software:<row id>`.
- **D4 Deletion.** Deleting a Kit audits the row (`deletions.log("kits", …)` with
  `_members` in the snapshot) and the database drops its memberships; Documents cascade by
  hook. Deleting an Item or a Software runs a **composed delete hook** — documents *and*
  `kit_members` — after the audit. A membership whose member row is gone is skipped on read.
- **D5 Engine reuse** (ticket (#106)):
  a `CardCollection(slug="kits")` supplies create / dirty-diff update / delete-with-audit,
  photo routes and Documents. The engine gains two seams: an **overridable page render**
  (the Kit page is `kits.html`, not the sectioned board) and the modal markup extracted to a
  shared partial `_card_modal.html`; `card-editor.js` drives the Kit modal unchanged with
  `rowSelector` = the sidebar entries and `reloadOnUpdate: true`. New code is the membership
  route and the member-resolving read (`app/kits.py`, `app/routers/kits.py`).
- **D6 URLs and page.** `GET /kits` renders the first Kit by name (or an empty state with
  "New kit"); `GET /kits/{id}` one Kit. Variant B: sidebar ("＋ New kit", Kits with cover
  thumbnail and count), full-bleed cover hero (first Kit photo, else first member photo),
  stats line, "How to use" (server-rendered by `documents.render_markdown`) and "What's in
  it" panels, a photo grid of members in `position` order (`SW` badge; status badge when the
  software is not active), then the transfer list. Nav: Inventory ▾ → Kits, after Software.
- **D7 Transfer list.** Available = every Item and Software (any Status) not in this Kit,
  by title, filtered by the app's one Search rule (`app/search.py`, JS mirror reused);
  "in N kits" hint for shared members. Click to multi-select, → / ← move and save at once
  through **`POST /api/kits/{id}/members {add: [...], remove: [...]}`**, which appends at
  `max(position)+1`, ignores unknown keys and duplicates, and returns the member list.
- **D8 Member tiles.** An inventory tile opens `/inventory/{id}/sheet`; a software tile
  opens `/software?q=<name>`; the ↗ Link is a corner icon whose click never follows the tile.
- **D9 Edit modal.** "Edit kit" on the hero, "New kit" in the sidebar. Fields: Name
  (required), Description, How to use (textarea with a 300 ms debounced preview beneath it
  via `POST /api/documents/render`); then the photo gallery, the Documents block, Delete
  (returns to `/kits`). The Kit modal may be wider than the boards' 560 px. No ID line.
- **D10 Item side** (ticket (#107)):
  `CardCollection.kits_enabled` — rows carry `_kits: [{id, name}]` from **one query**
  (`kit_members.list_for_members`), the delete hook composes the kit cascade, and
  `card-editor.js` renders a read-only **Kits** chips block under the form grid (style of
  Software's facts rows), each chip linking to `/kits/{id}`, hidden when empty. The Item
  sheet gets a Kits row; the bundle's `item.md` front matter a `kits:` list of names.
  Boards' grouping, filters and Search are untouched; membership is edited only on the Kit
  page.
- **D11 Seeding.** `scripts/seed_kits.py` reads `scripts/kits-seed.json` (the seven
  prototype kits: names, text, member business ids), resolves members to row ids,
  idempotent by Kit name; run once by hand.
- **D12 CSP.** No inline handlers; one nonce'd `<script>` per page for `window.KIT` /
  `window.CARD`; everything else in static files.

## Slices (as built, 2026-10-03)

1. `feat(store)`: `0012_kits.sql`, `store/kits.py`, `store/kit_members.py`, data-health section,
   schema doc — PR #118.
2. `feat(card-collection)`: `kits_enabled`, `_card_modal.html`, `template` + `page_context`,
   the chips block — PR #119.
3. `feat(kits)`: `app/kits.py`, `routers/kits.py`, `kits.html`, `kits.js`, nav; `card-editor.js`
   `onCreated` / `onDeleted` and the exposed Search helpers — PR #120.
4. `feat(inventory, software)`: both boards on, the sheet's Kits row, `kits:` in the bundle
   front matter — PR #121.
5. `feat(scripts)`: `scripts/seed_kits.py` + `scripts/kits-seed.json` — PR #122.
6. `docs`: this plan, CHANGELOG, glossary (Kit page, Transfer list), README; the
   `proto/functional-groups` branch deleted (its notes live in issue #104).

One deviation from D4: a deleted Kit's memberships are audited as `kit_members` rows in the
deletions log beside the Kit row, not embedded in the Kit's snapshot — the same facts,
recoverable per row, through the engine's unchanged audit path.

## Follow-ups (out of scope)

- A Kit sheet / export (print, PNG, bundle) in the shape of the Item sheet.
- Member reordering (drag) if order-added proves wrong in use.
- Kit totals in any report; group-by or filter by Kit on the boards; Kits in
  future-purchases; a Kit clipper.
