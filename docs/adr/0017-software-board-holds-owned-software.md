# Software: its own board for what you run, with a deterministic clipper

Decided 2026-09-30 (plan: `docs/plans/2026-09-30-003-feat-software-board-plan.md`).
Ported from future-purchases' Software board (its ADR-0006) onto the SQLite store
(ADR-0011, ADR-0012) and this app's security headers.

The Inventory tracks physical things you own. Software you *have* — installed, subscribed,
in use — does not fit the physical Item: its identity is a package key
(`pacman:ripgrep`, `github:owner/repo`, `appstore:904280696`), not a model number; it is
"installed on hosts", not "moved to a room"; its cost is a billing cadence, not Qty × Unit
cost with a salvage value. Bolting those fields onto the Item would grow every physical
item's modal, and a `Software` inventory Category would have no cadence, no install
locations and no import identity.

So **Software is its own entity** on its own `software` table and its own board
(`/software`, in the Inventory ▾ menu), built as one more CardCollection adapter — the
move Accounts and Inventory already made. The boundary with future-purchases is
ownership: its Software board holds software under consideration and upgrade paths; this
one holds what you run. Nothing migrates automatically between them.

What the entity commits to:

- **`Source_Key` is the identity** for idempotent upserts: written by the importer and the
  clipper, derived from a registry Link on a hand-made card, editable so a manual card can
  be linked later. A partial unique index enforces it; the adapter refuses a duplicate with
  a readable 400 before the index can.
- **`Install_Locations` are per host + manager** (`{host, manager, id, version, seen_at}`),
  so one card can be installed on the Linux box via pacman and on the Mac via brew.
- **Import is an HTTP contract**, `POST /api/software/import`, the same run shape
  future-purchases' `scripts/export_installed.py` produces. A run speaks for one host and
  names the managers it collected, so a partial run never uninstalls what it did not look
  at; re-posting the same run is a no-op. There is no bearer-token bypass and CSRF covers
  every POST, so a script cannot curl it: the board offers an **Import run** file picker,
  and the logic lives in `app/software_import.py` for a later in-process script.
- **Status is automatic only while it equals `_import_status`**, the last value the
  importer set. Once edited by hand the importer leaves it alone. Field ownership is
  explicit (`software_item.OVERWRITE_FIELDS` / `FILL_FIELDS`); everything else is set on
  insert only.
- **Registry-owned facts never pass through the modal.** Stars, latest version, licence
  id, repo and homepage, bundle id, topics and the install locations are stored-only:
  shown read-only in the modal, written by the importer and by `POST /api/software/{id}/facts`
  (the clipper today, a "refresh from source" later). The modal's whitelist cannot null
  them, and `/facts` cannot touch Status, Cost, Notes, Category or the name.
- **The clipper is deterministic and parses no HTML on the server.** GitHub, PyPI, npm,
  the iTunes Lookup API and formulae.brew.sh serve open JSON, fetched server-side (with an
  optional `GITHUB_TOKEN`); for any other page the bookmarklet harvests Open Graph and the
  schema.org `SoftwareApplication` node off the live DOM and the server maps that. No AI.
  The clip follows this app's shape — prepare, tick, apply through the board's own routes —
  not future-purchases' one-shot insert, and the popup (`clip.html` + `clip.js`) is now
  one page driven by `window.CLIP`, shared by every clipper.
- **One Clippers page** (`/clippers`) hands out every bookmarklet; the old per-board setup
  URL redirects there.

Considered and rejected: extra fields on the physical Item (above); software as an
inventory Category (above); copying future-purchases' `/api/clip` insert (it bypasses the
board's whitelist, minting and dirty-diff rules, ADR-0007); a server-side HTML parser
(BeautifulSoup is not a dependency here, and the bookmarklet already has the DOM).

_Consequences:_ the card engine gained `group_options` / `default_group` (a Group-by
toggle), `entry_sort`, `link_field` (a ↗ icon on each card) and `default_status`; cards are
`<div role="button">` so the link can nest, and the status filter's handler moved from an
inline `onchange` (which the nonce-only CSP was silently blocking, on Accounts too) into
`card-editor.js`. The clip popups carry a route-owned CSP with `https:` images so harvested
thumbnails preview (they could not before). Photos share the one photo store with
inventory (ids are random; no table prefix; `blobs` rows since ADR-0020). Follow-ups: refresh-from-source, the
exporter script and Mac collectors, `Merchant_Match` against the ledger, and narrowing
future-purchases' board to prospective software.
