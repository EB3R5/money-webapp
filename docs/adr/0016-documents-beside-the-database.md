# Documents: text inline, files beside the database, framed only in a sandbox

_Status: the files-beside-the-database part is superseded by ADR-0020 (2026-10-04) — a file Document's bytes are a `blobs` row keyed by the document id; the text-inline rule, the kinds, the rendering and the sandbox stand._

Decided 2026-09-30 (plan: `docs/plans/2026-09-30-001-feat-inventory-documents-plan.md`).
Lifted from tasks-webapp's per-task documents and adapted to ADR-0010 (files beside the
database) and the security headers of `docs/SECURITY.md`.

An Item carries **Documents**: manuals, receipts, warranties, and written notes. One row per
attachment in `documents`, keyed by `(parent_table, parent_id)` rather than an inventory
foreign key, so any CardCollection can turn the feature on (`documents_enabled`) without a
schema change; the parent is named the way `deletions.collection` already names it. There is
no SQL foreign key: the parent is polymorphic and the cascade is done in code with an audit.

Two storage shapes behind one rule, decided by the file's extension first and its content
type second: `.md` and `.txt` are **text documents**, decoded as UTF-8 and kept inline in
`body` so they can be edited in-app (a Note is a Markdown document created blank); every
other upload, `.html` included, is a **file document**, bytes at
`DATA_DIR/documents/<parent table>/<parent id>/<document id>.<ext>` with the row keeping the
extension. Paths come only from row ids and a checked suffix, never from the uploaded name.

Rendering happens once, on the server: markdown-it-py renders and nh3 sanitizes, and the
editor's live preview calls the same function, so there is exactly one place XSS can be
reasoned about. Plain text is escaped. **An uploaded HTML page is never inlined and never
runs on the app's origin.** The document page frames it in
`<iframe sandbox="allow-scripts allow-forms allow-popups">`, and the raw response carries a
`Content-Security-Policy: sandbox …` of its own, so even opened directly in a tab the page
has an opaque origin: its scripts may run but cannot read the session cookie or call the
API. A PDF is framed without a sandbox (Chrome will not run its viewer inside one) for the
browser's own viewer; a raster image (the photo allow-list) is shown with `<img>`; anything
else, SVG included, is a download.

The app's security headers deny framing everywhere (`frame-ancestors 'none'`,
`X-Frame-Options: DENY`). The raw route is the one place that sets those two headers itself
(`frame-ancestors 'self'` / `SAMEORIGIN`, plus the sandbox for HTML), and
`SecurityHeadersMiddleware` leaves a response's own CSP and X-Frame-Options alone
(`ROUTE_OWNED_HEADERS`); every other header is still stamped. The embed decision comes from
the stored content type, never from the extension.

Edits are dirty-diffs (ADR-0007): a save carries only `name` and/or `body`, so a rename and a
body edit never clobber each other. Renaming a text document re-classifies it (`a.md` →
`a.txt`); a file document's kind never changes.

Deleting a document audits the row to `deletions` and removes its file (a file already gone
does not block). Deleting an Item runs the collection's delete hook: every document row is
audited and removed, and the files stay on disk with the photos (ADR-0005 addendum), so a row
restored from `deletions` finds its bytes.

_Consequence:_ PDFs and HTML pages open in place, as the browser renders them (a desktop
shell without a PDF viewer shows a download instead). A note over the 64 KB JSON limit still saves because `/api/documents/` posts use the upload limit
(`TEXT_BODY_PATHS`); the domain cap is 1 MB of text. Orphaned document files, like orphaned
photos, wait for an offline prune. Recovery of a deleted document is manual: re-insert the
`deletions` snapshot and the file is still there.
