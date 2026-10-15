---
title: Inventory Item Export - Plan
type: feat
date: 2026-09-04
topic: inventory-item-export
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Inventory Item Export - Plan

## Goal Capsule

- **Objective:** Export one inventory Item as a self-contained bundle: a zip that unpacks to
  a folder holding `item.md` (front matter + body), `card.png` (the Item sheet as rendered)
  and `photos/` (the stored originals). Reached from a new read-only Item sheet page that is
  also the browser's print-to-PDF source.
- **Product authority:** This document. Decisions confirmed in dialogue 2026-09-04 (grill
  session, 15 questions): zip download (not write-to-disk); browser captures the PNG and posts
  it; a dedicated sheet page rather than screenshotting the edit modal; two-click explicit
  flow; curated sheet with blanks hidden; first photo is the hero; front matter with raw field
  names; cleaned name + short id folder; date in front matter only; originals untouched;
  link on both card and columns pages; export never blocked by missing photos; same-window
  navigation; export-fields rule beside the schema; print stylesheet included.
- **Stop conditions:** none open.

## Product Contract

### Summary

`/inventory/{id}/sheet` renders one Item: hero photo (first stored), thumbnails, name, brand,
model, Value, a spec table of the filled descriptive fields, notes. Its **Export bundle**
button captures the sheet as a PNG in the browser (html-to-image, as the report PNG buttons
do), posts it to `/api/inventory/{id}/export`, and downloads the zip:

```
Dyson V11 (a3f9)/
  item.md
  card.png
  photos/01.jpg
  photos/02.png
```

### Key Decisions

- **Zip, not folder-on-disk.** One delivery path that works in the desktop window and a
  browser tab. Save-to-folder via pywebview's dialog can layer on the same bundle builder later.
- **PNG comes from the browser.** Server-side rendering would need a headless browser or a
  hand-drawn card. The capture is optional: if it fails, the export proceeds without `card.png`.
- **Sheet, not modal screenshot.** The edit modal is a form; the columns detail pane has no
  photos. The sheet is the one layout the PNG, the print-to-PDF path and a future catalogue share.
- **Curated sheet.** `Salvage_Value`, `Useful_Life_Years`, `Classification` (`SHEET_HIDDEN`)
  stay out of the sheet and the Markdown table but remain in the front matter. Blank fields
  are hidden. Nothing is lost: the front matter carries every declared field.
- **Export fields live beside the schema.** `inventory_item.export_fields()` is the one
  statement of what an export carries (declared fields in order + Value, no internals), so a
  future CSV/JSON export reads the same rule.
- **Naming.** Folder = cleaned `Item_Name` + ` (<last 4 of _id>)`; photos numbered in stored
  order with the extension from their content type; fixed inner names `item.md`, `card.png`.
  The zip is named after the folder. Repeat exports are told apart by `exported_at` in the
  front matter; the browser de-duplicates the download name.
- **Originals, untouched.** No image library; full resolution is the point for claims.
- **Missing photos are skipped**, not fatal. An Item with no photos still exports (empty
  `photos/`, "No photo" placeholder on the sheet).
- **Same-window navigation.** pywebview has no tabs; a new-tab link would open a bare window
  without the session cookie. The sheet has a "Back to inventory" link.

## Surfaces

- `app/inventory_item.py` — `SHEET_HIDDEN`, `export_fields()`.
- `app/inventory_export.py` — pure: `folder_name`, `photo_ext`, `photo_paths`, `markdown`,
  `sheet_context`, `bundle`.
- `app/routers/inventory_export.py` — `GET /inventory/{id}/sheet`,
  `POST /api/inventory/{id}/export` (multipart, optional `png`). Photos read through the
  inventory board's `get_image` so the GridFS bucket is named once.
- `app/templates/inventory_sheet.html`, `app/static/js/inventory-sheet.js`,
  `app/static/css/app.css` (`.item-sheet*`, `@media print`).
- Card page: `extra_actions=[card-sheet]` on the inventory board; handler in
  `static/js/inventory.js` (hidden while creating). Columns page: the tree item carries
  `doc_id`; the detail pane shows an "Open sheet" link.
- `app/main.py` — `inventory_export` registered in `ROUTER_MODULES`.

## Verification

- `tests/test_inventory_export.py` — export_fields shape; folder/photo naming; Markdown front
  matter and body rules; sheet view-model; zip layout with/without PNG and photos; sheet page
  200/404; export skips a missing GridFS file and carries the posted PNG; columns tree
  exposes `doc_id`; the sheet action renders on inventory and not on accounts.
- Full suite green (289 tests).

## Open Questions / Deferred

- Save straight to a folder from the desktop app (pywebview folder dialog).
- Reorder photos in the modal to pick the hero (also fixes the card thumbnail).
- Date in folder/zip names if a history of claim bundles is kept.
- Resized copies alongside originals.
- Bulk / catalogue export: the sheet template over a list of Items.
