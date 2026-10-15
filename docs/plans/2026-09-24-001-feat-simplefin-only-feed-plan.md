# Replace the Tiller/Sheets feed with SimpleFIN, in this repo

## Context

money-webapp-next is the SQLite-first port of the household finance app. The SimpleFIN feed
(ADR-0014, `app/simplefin/`) already writes connections, accounts, transactions, and balance
snapshots through the stores, and a SimpleFIN setup token is now in hand with the bank linked.
The user wants SimpleFIN to replace the Tiller → Google Sheets → app pipeline, and asked
whether to calibrate in a separate repo first.

Two facts found while exploring decide the shape:

1. **The Sheets sync is already dead in this build.** `app/sheets_sync.py` still writes
   through the Motor handle to Mongo collections nothing here reads. Its UI (Sync buttons on
   Ledger and Balances, the Activity page's sheet-sync card, `POST /sync`) points at nothing.
2. **The port is only half done.** Ledger, Budgets, Categorization, Auth, Activity, Credit,
   Tax, Metrics, and SimpleFIN read the stores. Accounts, Balances, Inventory (+clip, columns,
   export), Investments, Dashboard, Reports, Category insights, and the Data page still import
   the Motor handle, as do the shared modules they lean on (`card_collection`,
   `grid_collection`, `registry`, `lookups`, `audit`, `snapshot`, `savings`, `tax`, `credit`,
   `financial_health`, `investments`, `inventory_sync`, `category_mapping`, `rollup_mongo`).
   Tests pass because 22 test files still use the mongomock `client` fixture. money-next
   cannot serve those pages without Atlas today, and the feed writes into tables
   (`accounts`, `balance_history`) whose pages are among the unported ones.

**Answer to the repo question: build it here, no calibration repo.** The feed, the stores, the
schema, and the tests it needs all live here; a second repo would duplicate the store layer to
learn something a scratch `DATA_DIR` in this repo can show in an afternoon. Calibration is a
slice below (15), not a repo. The feed's data being simpler than Tiller's is fine: the app
already computes the derived fields from Category (ADR-0006), and nothing reads Tiller's
`Week` or `Check Number`.

## Decisions (made with the user, 2026-09-24)

- **D1 Prerequisite:** finish the port first. Every remaining section moves to the stores and
  the mongomock fixture goes. Only then does money-next run on SQLite alone.
- **D2 Seam:** small overlap plus a one-off seam reconciliation. The feed starts a few days
  before the last Tiller row; a script pairs feed rows with Tiller rows (same account, same
  Amount, Date within 3 days, description prefix match, exactly one candidate) reusing the
  pending-reconciliation logic; the feed row takes the Tiller row's app-owned fields, the Tiller
  twin is audited to `deletions` under a new reason and deleted. Unmatched Tiller rows stay as
  history.
- **D3 Linking:** feed accounts arrive **unlinked** and hidden from cards. A Link action on the
  Accounts page attaches one to an existing card (sets `simplefin_account_id` on the card's
  row, repoints the feed's transactions and snapshots, drops the placeholder) or promotes it to
  a new card.
- **D4 Sheets code:** delete it all. `app/sheets_sync.py`, `routers/sync.py`, the Sync buttons,
  `tiller_sync/`, the `migration/` pipeline, the Sheets config vars, the sheet-sync data-health
  scope. Tiller rows stay as history. ADR-0015 records SimpleFIN as the only live feed.

Grilled on 2026-09-24, one question at a time:

- **D5 Timeline:** the Mongo app and its Tiller sync keep running through Phases 1 to 3. On
  cut-over day: a fresh Atlas export seeds money-next, the feed starts a week before that
  export's last Tiller row, the seam reconciles the overlap, Tiller stops.
- **D6 Snapshot cadence:** one balance Snapshot per account per **calendar day**, latest run
  wins (upsert on account + day; the row keeps the latest `sync_run_id`). Replaces the
  per-run uniqueness from the earlier feed decision. Tiller history stays daily; the feed's
  four runs a day do not quadruple `balance_history`.
- **D7 Auto-categorization on sync:** after each chunk's inserts the sync runs the Rule engine
  batch (first match wins, same engine as the Ledger's "Apply rules") on the new rows, then
  the ML suggest batch on rows still blank. The Sync run records how many rows each touched.
  ML still only suggests; nothing else changes about the two engines.
- **D8 Ignore:** a third action beside Link and Promote. An ignored feed account stays as a
  hidden row so it is not re-offered, and future syncs skip its transactions and snapshots.
  Reversible from the same strip.
- **D9 Undecided accounts collect:** between first appearance and the Link/Promote/Ignore
  choice, rows land under the placeholder's name; Link renames them onto the card. Nothing is
  missed while deciding.
- **D10 Account #:** feed rows carry none. From-account inheritance and the snapshot writer key
  on Account ID instead. Tiller history keeps its values; the column stays for display.
- **D11 Descriptions:** stored raw in both Description and Full Description. The calibration
  slice measures the rule hit-rate gap; a normalizer is a follow-up slice only if the numbers
  call for one.
- **D12 Delivery:** ten Phase 1 slices, one section per PR into `main`; filed as a parent
  issue plus `ready-for-agent` sub-issues, the same way the Categorization and SimpleFIN plans
  were.

## How it is filed

Same shape as the Categorization and SimpleFIN plans: this document lands as
`docs/plans/2026-09-24-001-feat-simplefin-only-feed-plan.md`, one parent issue
("SimpleFIN replaces the Sheets feed; the app runs on SQLite alone", label `enhancement`, plan
attached as the first comment), and one `ready-for-agent` sub-issue per slice with
`## Parent / ## What to build / ## Acceptance criteria / ## Blocked by` and native blocking.
One PR per slice into `main` (the `sqlite` branch is merged; new work goes straight to `main`
on `port/<section>` or `feat/<name>` branches).

Patterns every port slice copies: `app/routers/ledger.py` (a `Grid` over a store replaces
`GridCollection`), `app/rollup.py` (the store-side twin of `rollup_mongo.py`),
`app/store/deletions.py` `log()` (the twin of `app/audit.py`), the `store_client` fixture and
`tests/dbhelper.py` seeds. Each port slice moves its own test files off the mongomock `client`
fixture onto `store_client`, adding seeds to `dbhelper.py` that mirror the rows the `client`
fixture inserts today. Store helpers that do not exist yet (`distinct`, an update-where, a
latest-per-account query) are added to `app/store/base.py` or the entity store as the slice
needs them, never as a generic layer up front.

## Phase 1 — finish the port (D1)

1. **Balances on the stores.** `app/routers/balances.py` over the `balance_history` store; the
   grid's "Account Type" column maps to the store's `Type` key (the export already folded
   `Type__15`; the feed's `_snapshot` writes `Type`/`Class` the same way). From-account
   stamping reads `accounts.get` and inherits Institution and Class from the newest prior
   snapshot by "Account ID" (Account # is no longer inherited or required, D10). `app/snapshot.py` writes through `balance_history`; `app/audit.py`
   delegates to `deletions.log`. AC: Balances page renders, pages, sorts, searches from SQLite;
   from-account stamps a row; balances and snapshot tests green on `store_client`; no Motor
   import in the router. Blocked by: none.
2. **Registry and its domains (credit, category mapping).** `app/registry.py` over stores:
   `ConfigDoc` over `metrics_config`, add/update/delete taking a `Store`, audit via
   `deletions.log`. `app/credit.py` moves its balance-history reads (latest balance per
   account, distinct names) and its transactions query to store methods.
   `app/category_mapping.py` over the two mapping stores. AC: Credit page and CRUD on SQLite;
   `test_credit`, `test_registry`, `test_category_mapping` green on `store_client`;
   `scripts/seed_credit.py` uses the stores. Blocked by: none.
3. **Tax, savings, financial health.** `app/tax.py`, `app/savings.py`,
   `app/financial_health.py` swap registry and `db` calls for the ported registry and store
   queries. AC: Tax, Metrics, Health-metrics pages and CRUD on SQLite; their tests green on
   `store_client`. Blocked by: 2.
4. **Rollup consumers: dashboard, category insights, reports, metrics, tax routers.** Import
   `app/rollup.py` instead of `rollup_mongo`; the dashboard's aggregate and the insights page's
   five become rollup functions (single-owner rule); `rollup_mongo.py` and its test are
   deleted, cases moved to `test_rollup`. AC: the five pages render from SQLite; nothing
   imports `rollup_mongo`; `test_dashboard`, `test_category_insights`, `test_reports`,
   `test_report_png` green on `store_client`. Blocked by: 3.
5. **Lookups and the Categories page.** `app/lookups.py` `LookupContext` gains a store and a
   target store per context (categories→transactions, account categories→balance_history,
   inventory categories→inventory); sections, items, field options, and cascades through store
   calls; `delete_item` audits via `deletions.log`; the `Type__15` alias goes. AC: all three
   Categories contexts add, rename, edit, delete with cascades on SQLite; `test_categories`,
   `test_inventory_taxonomy` green on `store_client`. Blocked by: 1.
6. **CardCollection and the Accounts page.** `app/card_collection.py` takes a `Store` (base
   query becomes a where dict), images via `app/store/files.py`. `routers/accounts.py`: the
   type-aware create fans out to the `portfolio` and `credit_accounts` stores, the overlay uses
   the queries from slice 2, lifecycle updates the stores, and the accounts query excludes
   `is_hidden` rows (prepares D3). AC: Accounts cards from SQLite, create fan-out to detail
   record plus first Snapshot, archive and reopen, edit veto on linked cards;
   `test_account_entry`, `test_card_collection` green on `store_client`. Blocked by: 1, 2.
7. **Inventory section.** The four inventory routers plus `app/inventory_clip.py`,
   `app/inventory_sync.py`, `app/inventory_item.py` over the `inventory` and
   `inventory_categories` stores and the files layer. AC: page, clipper, columns, export, and
   rollup-to-Snapshots on SQLite; `test_inventory_*`, `test_files` green. Blocked by: 6.
8. **Investments section.** `app/investments.py` and its router over `portfolio` (closed flag
   as a column) and `balance_history`; refresh and sync append Snapshots through
   `snapshot.append`. AC: page, price refresh, holding edits, portfolio→Snapshots sync on
   SQLite; `test_investments` green. Blocked by: 6.
9. **Data page over SQLite tables; retire GridCollection.** `routers/sheets.py` becomes
   `routers/data.py`: tables from `sqlite_master` minus the hidden set, columns from
   `PRAGMA table_info`, one generic Grid with LIKE search; **only `autocat` editable, everything
   else read-only** (decisions from the map's Sheets-grid and Data-page tickets).
   `app/grid_collection.py` deleted; `test_grid_collection` becomes the Data page test.
   AC: `/data` browses every table, edits only autocat; no `GridCollection` import remains.
   Blocked by: 1, 7.
10. **Retire Motor and mongomock.** Delete `app/db.py`; drop `MONGO_URI`/`MONGO_DB` from
    config; delete the `client` fixture and its seeds from `tests/conftest.py`; drop
    `motor`, `pymongo` (keep only under the `[export]` extra for the one-time census), and
    `mongomock-motor` from the dependencies; adjust `test_demo_live`, `test_census`. AC: no
    file under `app/` or `tests/` imports `db`, `motor`, or `mongomock`; suite green; the app
    starts with only `DATA_DIR` and `SESSION_SECRET`. Blocked by: 2 through 9.

## Phase 2 — remove the Sheets path (D4)

11. **Delete the Sheets sync and its UI; ADR-0015.** Delete `app/sheets_sync.py`,
    `app/routers/sync.py`, `tiller_sync/`, `migration/`, `tests/test_sheets_sync.py`; remove
    `GOOGLE_SA_JSON`, `SHEET_ID` (the hardcoded real id goes with it), `TXN_TAB`, `BALANCE_TAB`
    from config, `.env.example`, `compose.yml`, `docs/deployment.md`, `docs/SECURITY.md`;
    remove `register_sheets_job` from `app/main.py` and the sync router from `ROUTER_MODULES`;
    remove `wireSyncButton` from `grid-factory.js` and the Sync buttons from `ledger.html`,
    `balances.html`, `ledger.js`, `balances.js`; remove `data_health._sync_status`, the
    Activity page's "Last sheet sync" card and "Sync status by scope" table, and their test;
    delete `app/store/sync_state.py` with a `0006_drop_sync_state.sql`. Write
    `docs/adr/0015-simplefin-only-feed.md`: SimpleFIN is the only live feed; supersedes the
    sync half of ADR-0013 and the "Sheets sync keeps working" consequence of ADR-0014; Tiller
    rows stay as history (`source IS NULL` or `sheet_sync`). `CONTEXT.md`: replace "Sheets
    import" with **Tiller row (history)**, **Feed account**, **Linked account**, **Seam**;
    README, CHANGELOG, `docs/open-source.md` updated; `docs/schema.mmd` regenerated. AC: no
    file mentions `sheets_sync`, `GOOGLE_SA_JSON`, `SHEET_ID`, or `/sync/status`; Activity
    shows only the SimpleFIN block; suite green. Blocked by: 10.

## Phase 3 — the feed as the primary source (D3, D6, D7, D8, D9)

12. **Daily Snapshots and categorization on sync.** `_snapshot` in `app/simplefin/sync.py`
    upserts on (account, calendar day of `balance_date`): a later run the same day replaces
    Balance, `available`, and `sync_run_id`. Schema `0007_snapshot_per_day.sql` drops
    `ux_balance_history_run` for a unique index on `(account_id, date) WHERE source =
    'simplefin'`. After each chunk's inserts, `apply_accountset` calls the Rule engine batch
    from `app/categorization.py` (the same function the Ledger's "Apply rules" uses) on the
    newly inserted row ids, then `suggest_batch` on those still blank; `SyncSummary` and
    `sync_runs` gain `rules_applied` and `ml_suggested` counts, shown on the Activity page.
    AC: two runs the same day leave one snapshot per account carrying the second run's
    values and id; a rule matching a new feed row categorizes it in the same run and the
    derived fields are filled; a blank row gets Pred fields; counts appear in the run row and
    on Activity; existing pending and window tests still pass. Blocked by: 11.
13. **Feed accounts arrive unlinked; Link, Promote, and Ignore.** `_upsert_account` inserts
    the placeholder with `is_hidden=True`, `Status="Unlinked"`; its transactions and
    snapshots still land under the placeholder's name (D9). New `app/simplefin/link.py`:
    `unlinked()` lists placeholders; `link(feed_id, card_id)` copies the feed columns
    (`simplefin_account_id`, `connection_id`, `currency`, `available`, `balance_date`,
    `last_seen_at`) onto the card, renames the feed's transactions to the card's Account and
    Institution by `provider_account_id`, re-keys the placeholder's snapshots to the card's
    Account ID, audits the placeholder (`reason="feed_linked"`) and deletes it;
    `promote(feed_id, kind)` applies the `ACCOUNT_TYPES` preset from `routers/accounts.py`,
    mints an Account ID, clears `is_hidden`, sets Status; `ignore(feed_id)` sets
    `Status="Ignored"` (still hidden) and `unignore` reverts it. The sync skips transactions
    and snapshots for ignored accounts. No Account # is written anywhere (D10); balances
    inheritance and the snapshot writer key on Account ID. Store methods:
    `accounts.unlinked()`, `transactions.rename_account(...)`,
    `balance_history.rekey_account(...)`. AC: a sync into a data dir with a Tiller-era card
    creates no visible second card; after link, the earlier rows carry the card's name and a
    further sync writes under it; promote yields a classified card; an ignored account's rows
    are skipped on the next run and its earlier rows are audited and removed; all audited;
    tests extend `tests/test_simplefin_sync.py` with its `client_for`/`payload()` seam.
    Blocked by: 6, 12.
14. **Link strip on the Accounts page.** An "Unlinked feed accounts" strip on the card page
    (accounts only), each row with "Link to…" (select over active cards), "Promote as…"
    (select over account types), and "Ignore"; an "Ignored" fold-out to un-ignore. Routes
    `GET /api/accounts/unlinked`, `POST /api/accounts/link`, `POST /api/accounts/promote`,
    `POST /api/accounts/ignore`, registered before the CardCollection routes like
    archive/reopen. AC: strip appears only when unlinked rows exist; each action refreshes
    the page; tests through `store_client`. Blocked by: 13.

## Phase 4 — the seam and calibration (D2, D5, D11)

15. **Seam matcher and one-off reconciliation.** Generalize `transactions.pending_twins` into
    a `twins(...)` query with a source filter (the pending variant keeps its signature).
    `app/simplefin/seam.py` reuses `pending.descriptions_match` and the exactly-one rule: for
    each linked feed row in the overlap window, candidates are Tiller rows (`source IS NULL OR
    source='sheet_sync'`) with the same Account name, exact Amount, Date ±3; one candidate →
    carry `pending.CARRY` plus Tiller's `Transaction ID` onto the feed row,
    `deletions.log(reason="seam_replaced")`, delete the twin; zero or many → leave. CLI
    `python -m app.simplefin.seam [--dry-run] [--since] [--account]` prints counts only
    (matched, unmatched feed, unmatched Tiller, ambiguous, per account). AC: `tests/test_seam.py`
    covers one, zero, and many candidates, prefix descriptions, carried fields, the audit
    reason; a dry run writes nothing. Blocked by: 13.
16. **Calibration report and scratch-dir procedure.** `scripts/feed_calibration.py
    --data-dir <scratch> --since YYYY-MM-DD`, counts only: per account Tiller vs feed rows in
    the window, seam match rate and ambiguity count, rules-engine hit rate over feed rows vs
    Tiller rows in the same window, Description length stats per source, count of feed rows
    whose Institution differs from the linked card's, Amount sign agreement per account.
    `docs/runbooks/feed-calibration.md`: copy the seeded data dir, link accounts, run the feed
    with `--since`, run the report, iterate. AC: the script runs against `store_db` in a test
    and prints no row contents; runbook in docs. Blocked by: 15.
17. **Cut-over runbook and glossary close-out.** `docs/runbooks/cut-over.md` (D5): fresh
    Atlas export → seed, census diff, link/promote/ignore every feed account, feed `--since`
    one week before the export's last Tiller row, seam dry run then real run, census counts
    before and after, scheduler on, Tiller sync stopped in the Mongo app the same day. Final
    `CONTEXT.md` and CHANGELOG pass. AC: runbook reviewed; nothing in it prints row contents.
    Blocked by: 16.

## What the calibration slice measures (decided, not open)

- **Description quality** (D11): rule hit rate over feed rows vs Tiller rows in the same
  window, and description-length stats. A normalizer in `_upsert_transaction` is a follow-up
  slice only if the gap is material.
- **Amount sign for liabilities.** Verified before the seam matches on exact Amount; if the
  feed reports the bank's sign where Tiller stored magnitudes, the seam matches on absolute
  value per account kind.
- **Institution drift.** Slice 13 backfills the card's Institution onto feed rows; the report
  counts rows where they still differ.
- **Tiller `source` values in the export** (`NULL` vs `sheet_sync`): a counts query before
  slice 15's filter is frozen.

## Verification

- Every slice: `pytest -q` green; the slice's pages swept in a browser against a seeded
  scratch data dir (no Atlas). Phase 1 ends with the app started from an empty environment plus
  `SESSION_SECRET` and `DATA_DIR`, every page 200.
- Phase 2: a grep for the deleted names is empty; `docker compose config` on both compose files
  passes without the Sheets variables.
- Phases 3 and 4: on a **copy** of the seeded data dir, link each bank account, run the feed
  with `--since` a week before the export's last Tiller date, run the seam dry-run and read the
  counts, then the real seam; `scripts/db_census.py --diff` before and after shows only the
  expected transaction delta. Nothing printed contains a row.
- The production `money-next` service stays as defined; only its `.env` changes (no Sheets vars).
