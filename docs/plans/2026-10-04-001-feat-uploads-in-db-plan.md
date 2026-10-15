---
title: Uploads in the database - Plan
type: feat
date: 2026-10-04
topic: uploads-in-db
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Uploads in the database - Plan

## Goal Capsule

- **Objective:** Every upload lives in `money.sqlite`. The bytes of every photo (the
  `images` entries of `inventory`, `software` and `kits`) and of every file Document move
  from files beside the database into a `blobs` table, so a copy of the database is a copy
  of what a person uploaded and nothing drifts between a folder and a file. Text Documents
  were already inline (ADR-0016); the ML model stays a file.
- **Product authority:** This document and ADR-0020. Decisions confirmed in dialogue
  2026-10-04. Execution parent: #126; slices #127–#132.
- **Stop conditions:** none open.

## Key Decisions

- **D1 Scope.** Photos on all three card tables and file Documents move. The model stays
  under `models/`: it is retrained in one click and 25 MB per retrain would be database churn
  for something not irreplaceable.
- **D2 On owner delete.** A Blob outlives its owner (the ADR-0005 addendum guarantee: a row
  restored from `deletions` finds its bytes). Deleting one photo or one Document still deletes
  its Blob. `scripts/prune_blobs.py` (dry-run by default, `--apply`, `--no-vacuum`) removes
  Blobs no live row or deletion snapshot references and VACUUMs with the app stopped. This
  replaces the `prune_photos.py` ADR-0005 named and that was never written.
- **D3 Process.** Parent issue with ready-for-agent slices, docs PR first, plan PR, slice
  PRs, closeout.
- **D4 Ids are keys.** A photo entry's `id` and a file Document's row id are the Blob id;
  `blobs.kind` (`photo` | `document`) separates the namespaces. The `images` JSON shape,
  `/api/{slug}/image/{id}`, `/api/documents/{id}/raw`, the Item bundle and the clippers are
  unchanged; the image route serves by id and the per-table `with_photo` scans go.
- **D5 No fallback read from disk.** New code reads only `blobs`. Production is not rebuilt
  between merging slice 1 and running the one-time move (deploy freeze, stated on #126).
- **D6 The move verifies before it deletes.** `scripts/move_files_into_db.py` inserts, reads
  back, compares sha256, then unlinks; exit 1 on mismatch, 2 on a missing or unreadable
  referenced file; files no row names are listed and left alone; idempotent and restartable.

## Product Contract

### Summary

No user-visible change. Photos and Documents upload, show, download and delete exactly as
before. Backups become `money.sqlite` (plus `models/`). Routine backup cadence stays
undecided (#19).

### Data

Migration 0014, one statement:

```sql
CREATE TABLE blobs (
    id           TEXT PRIMARY KEY,   -- photo entry id (uuid hex) or documents.id
    kind         TEXT NOT NULL,      -- photo | document
    content_type TEXT,
    size         INTEGER NOT NULL,
    sha256       TEXT NOT NULL,
    created_at   TEXT,
    data         BLOB NOT NULL       -- last, so metadata reads skip the overflow pages
);
```

`app/store/blobs.py` is hand SQL (`base.py` has no bytes kind): `put`, `new_photo`, `get`,
`meta`, `delete`, `ids`, `totals`, `referenced_ids`, `unreferenced`. The upload allow-list
(`EXTENSIONS`, `extension_for`, `document_ext`) moves there from `app/store/files.py`, which
becomes model-only. `blobs` is hidden on the Data page. `scripts/db_census.py` keeps its
`photos` and `documents` keys (counting Blob rows as "files") and adds a `blobs` section.

Referenced ids, for prune and census: the live `images` entries of the three tables, live
`documents` rows of kind `file`, the `_images` inside `deletions` snapshots of the three
tables, and the `_id` of `deletions` snapshots from `documents`.

## Slices (as built, 2026-10-04)

0. Docs first: ADR-0020 + glossary — PR #133; this plan — PR #134.
1. **Photos are Blobs** (#127) — PR #135: migration 0014, `app/store/blobs.py`,
   `card_collection.py` photo methods, `with_photo` removed, `inventory_export`,
   `export_atlas` (writer bound under a local name: its read-only guard test forbids
   GridFS's write spelling), census photos, `docs/schema.mmd`, `LATEST = 14`.
2. **File Documents are Blobs** (#128) — PR #136: `app/documents.py` upload/raw/delete,
   `files.py` model-only, `Database.subdir` removed, census documents + `blobs` section.
3. **One-time move** (#129) — PR #137: `scripts/move_files_into_db.py`,
   `docs/runbooks/uploads-into-db.md`. Exercised on a scratch copy of the real data first.
4. **Prune** (#130) — PR #138: `referenced_ids` / `unreferenced`, `scripts/prune_blobs.py`,
   census `blobs.unreferenced`.
5. **Cutover** (#131) — run 2026-10-04: 144 photos moved, 10.6 → 22.8 MB, census equal,
   container rebuilt healthy. Deviation: ownership was fixed through `docker exec … chown`
   rather than `sudo` (the operator shell has no passwordless sudo).
6. **Closeout** (#132): README, deployment, backups, SECURITY, CHANGELOG, this plan, map note.

Full suite 698 passed, 1 skipped; `schema_doc.py --check` green.

## Follow-ups (out of scope)

- Routine backups of the data directory (#19): now `money.sqlite` + `models/`; cadence and
  destination still to decide in `docs/backups.md`.
- #96 deletes `scripts/export_atlas.py`, which slice 1 only keeps running.
- A restore helper for `deletions` snapshots (today manual re-insert); Blobs make it complete.
