---
title: Inventory Documents - Plan
type: feat
date: 2026-09-30
topic: inventory-documents
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Inventory Documents - Plan

## Goal Capsule

- **Objective:** Attach documents to an inventory Item: uploaded files (manuals, receipts,
  warranty PDFs, photos of paperwork) and Markdown notes written in-app, the way tasks-webapp
  attaches documents to a task. A Documents panel in the Item's edit modal, a Document page
  per attachment (editor with live preview for text, download for files, inline for images),
  and an audited cascade when the Item is deleted.
- **Product authority:** This document. Decisions confirmed in dialogue 2026-09-30.
- **Stop conditions:** none open.

## Key Decisions

- **D1 Placement:** the panel lives in the CardCollection edit modal beside Photos, behind a
  `documents_enabled` flag (mirror of `images_enabled`). Inventory turns it on; Accounts does
  not. The Item sheet and the export bundle are untouched (follow-up).
- **D2 Kinds:** text kinds are `md` and `txt` only (inline `body`, editable, rendered
  server-side by markdown-it-py + nh3). Everything else, `.html` included, is kind `file`:
  bytes on disk. Raster images show via `<img>`; anything else downloads.
- **D2a Viewing (revised 2026-09-30, same day):** the user wants to read PDFs and review
  HTML in place. An HTML file document is framed in a sandboxed iframe, and its raw response
  carries its own `sandbox` CSP (opaque origin even when opened directly); a PDF is framed
  without a sandbox for the browser's viewer. The raw route owns its CSP and X-Frame-Options
  for those two kinds and the header middleware leaves route-set frame headers alone. No
  server-side rendering, so no compute cost: the browser renders.
- **D3 Cascade:** deleting Items audits every document row to `deletions` and removes the
  rows; files stay on disk (ADR-0005 addendum, same as photos). Deleting a single document
  from the UI removes its file.
- **Parent key:** `(parent_table, parent_id)` rather than `item_id`, so a second collection
  needs no schema change.
- **Body limit:** JSON posts under `/api/documents/` use the upload limit
  (`TEXT_BODY_PATHS`); the domain cap is 1 MB of text.
- **On-disk shape:** `documents/<parent table>/<parent id>/<document id>.<ext>`; every
  segment comes from the row, the extension from a checked suffix (`[a-z0-9]{1,10}`, else `bin`).

## Product Contract

### Summary

The Item edit modal gains a Documents panel (count, rows with kind chip / name link /
size and edited time / edit-rename-delete, Upload and New note buttons; both need a saved
Item). Upload posts multipart `files` to `POST /api/inventory/{id}/documents` and reports
per-file errors without failing the batch. New note posts to `POST /api/inventory/{id}/notes`
and opens `/documents/{id}?edit=1`.

`/documents/{id}` shows one document: Markdown rendered and sanitized, plain text escaped in
a `<pre>`, an HTML page in a sandboxed iframe, a PDF in a plain iframe, a raster image as
`<img>`, anything else as a download link. Text documents have
View / Edit modes; the editor previews through `POST /api/documents/render` (the same
renderer), saves with `POST /api/documents/{id}` `{updates:{body}}` on Save or Ctrl-S, and
warns before leaving dirty. Download and Print are always there.

`GET /api/documents/{id}/raw?download=0|1` serves the bytes with the row's content type;
`inline` for html / pdf / raster images with `download=0`, otherwise `attachment`. HTML
responses carry `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups`,
PDFs `frame-ancestors 'self'`, both `X-Frame-Options: SAMEORIGIN`. The auth gate covers it
like any page.

### Data

`documents` (schema 0010): `id, parent_table, parent_id, name, kind (md|txt|file),
content_type, size, body (text only), file_ext (file only), created_at, edited_at`, index on
`(parent_table, parent_id)`. The Item page ships each Item's list without bodies in one query.

## Slices (as built)

1. `feat(store)`: schema 0010, `app/store/documents.py`, document helpers in
   `app/store/files.py`, `docs/schema.mmd`, deps, `tests/test_files.py`.
2. `feat(documents)`: `app/documents.py`, `app/routers/documents.py`, `document.html`,
   `document.js`, CSS, the body-limit path override.
3. `feat(inventory)`: `CardCollection.documents_enabled` + `delete_hook`, page attach,
   parent routes, modal panel, `card-editor.js` block, `tests/test_documents.py`, security and
   census tests.
4. `docs`: ADR-0016, CONTEXT glossary (Document, Note, Data directory), CHANGELOG,
   `scripts/db_census.py`, this plan.

## Follow-ups (out of scope)

- Documents in the Item export bundle (`documents/` beside `photos/`).
- A drop zone on the modal; a back link that reopens the Item's modal.
- A prune script for orphaned `photos/` and `documents/` files (ADR-0005 names one that does
  not exist yet).
