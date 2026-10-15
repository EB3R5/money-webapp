# Uploads live in the database: photos and file Documents are `blobs` rows

Decided 2026-10-04 (plan: `docs/plans/2026-10-04-001-feat-uploads-in-db-plan.md`).
Supersedes the files half of ADR-0010 (`photos/` beside the database) and the on-disk half
of ADR-0016 (file Documents under `documents/`); amends the ADR-0005 addendum. The ML model
stays a file under `models/`, so what ADR-0010 says about it stands.

The bytes of every photo (the `images` entries of `inventory`, `software` and `kits`) and of
every file Document are rows of one table, `blobs(id, kind, content_type, size, sha256,
created_at, data)`, so `money.sqlite` alone holds what a person uploaded. The reason is
loss, not speed: a database copied without its folder, or a folder restored from an older
copy than the database, silently drops photos that cannot be taken again. With the bytes in
the row store, "back up the app" is one file, and the blob write and the owning row's update
commit in the same request, so an upload can no longer leave a file on disk that no row
names. Text Documents (`.md`, `.txt`) were already inline in `documents.body`; this closes
the split.

**Ids are keys.** A photo entry's `id` (the uuid the `images` list already carries) and a
file Document's row id are the blob id. The `images` JSON shape, `/api/{slug}/image/{id}`,
`/api/documents/{id}/raw`, the Item bundle and the clippers are unchanged; the image route
serves by id alone, and the per-table `with_photo` scans go. `blobs.kind` (`photo` |
`document`) keeps one namespace from serving the other. The `data` column is last so a
metadata read (prune, census) never pulls the overflow pages.

**A Blob outlives its owner.** Deleting one photo or one Document deletes its blob, as
removing the file did. Deleting an Item, a Software row or a Kit audits the row to
`deletions` and leaves its blobs, so a row restored from the snapshot finds its bytes: the
guarantee the ADR-0005 addendum gave to files. `scripts/prune_blobs.py` removes blobs that
no live row and no deletion snapshot references, dry-run by default, and VACUUMs; the
`prune_photos.py` that addendum named was never written. A deleted row's photo therefore
stays fetchable by its uuid, behind the login, until pruned.

**Why not keep files and fix backups instead.** Backups of the data directory are still
undecided (wayfinder #19), and a backup only protects what it copies together; the drift
between a database and a folder is the failure this removes. Why not the model too: it is
retrained in one click from categorized Transactions and is 25 MB per retrain, which would
be 25 MB of database churn each time for something that is not irreplaceable.

**The one-time move.** `scripts/move_files_into_db.py` walks every reference, inserts the
blob, reads it back, compares the sha256, and only then unlinks the file; a mismatch keeps
the file and fails the run, a missing or unreadable file is reported and fails the run,
files no row names are listed and left alone. It ran once, on 2026-10-04, and was removed
afterwards: a data directory created by this build has never had files beside the database.

_Consequence:_ the backup is `money.sqlite` (with its WAL, or via `sqlite3 .backup`) plus
`models/`. The database grows by the upload volume (about 12 MB today) and by one row per
upload; a 25 MiB upload is one row (SQLite allows 1 GB). Space from deleted blobs comes back
only through `prune_blobs.py --apply`, which VACUUMs and needs the app stopped. Path safety
(`docs/SECURITY.md` T12) now concerns only the model file.
