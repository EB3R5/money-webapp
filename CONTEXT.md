# money-webapp

The domain language of the household finance app. These are the terms the code,
templates, and views use. Keep new code consistent with the chosen words; the
`_Avoid_` lists name the synonyms we deliberately don't use.

## Data sources

**Feed**:
Where rows arrive from on their own: today only the SimpleFIN Bridge (ADR-0014, ADR-0015),
writing Connections, Accounts, Transactions, and Snapshots through their Stores and never
overwriting an app-owned field — or a Hand edit — on a row that already exists. A row's
`source` says which feed wrote it; a row a person typed has none.
_Avoid_: sync source, import, integration

**Tiller row (history)**:
A Transaction or Snapshot written before the feed existed (`source` NULL or `sheet_sync`): history that nothing refreshes.
_Avoid_: legacy row, imported row, migrated row

**Feed account**:
An Account row the feed created for a bank account it saw (`simplefin_account_id` set). It
arrives hidden with Status Unlinked, collecting its transactions and Snapshots under its own
name, until a person links it to an existing card, promotes it to a card of its own, or
ignores it (Status Ignored: still hidden, its rows removed, skipped by the sync from then
on). `app/simplefin/link.py` owns the three operations.
_Avoid_: provider account, synced account, placeholder

**Linked account**:
A card whose row carries the feed's identity (`simplefin_account_id`), so the feed's
transactions and Snapshots land under that card's name and Account ID.
_Avoid_: connected account, matched account

**Seam**:
The overlap where the feed's first rows met the last Tiller rows; reconciled once at cut-over (2026-09-25), its pairings recorded as `seam_replaced` in `deletions`.
_Avoid_: overlap, dedupe, migration window

## Ledger

**Transaction**:
One row in the `transactions` table — a dated money movement with an Amount,
Account, and Category. The Ledger page is the grid over these.
_Avoid_: entry, txn, line item, record

**Hand edit**:
A provider field (Date, Description, Amount, Account, Institution) on a feed Transaction
whose value a person changed, so it differs from the feed's last-applied value. A Sync run
keeps it, per field, whatever the bank sends later; the fields the person did not touch keep
following the bank. A pending row's Hand edits ride onto its posted twin. See ADR-0019.
_Avoid_: override, manual value, lock, correction (the bank's change is the correction)

**Category**:
The user-chosen classification of a Transaction, drawn from the fixed `categories`
table. Choosing a Category cascades its **derived fields** onto the Transaction.
_Avoid_: tag, label, bucket

**Starter taxonomy**:
The Categories a fresh database begins with, from `app/seeds/categories.json`: one row per
Category with its derived fields, in the vocabulary the reports read (Type Income / Expense /
Transfer; Budget Discretionary / Non-Discretionary; Cashflow Type Operating / Investing /
Financing / Fixed Asset Activities; Timing Monthly … One-Time). Written once by
`manage.py init_store` when the table is empty and never again; edited on the Categories page
like any other row.
_Avoid_: defaults, fixtures, template categories

**Derived fields**:
`Group`, `Budget`, `Cashflow Type`, `Timing`, `Type` — copied onto a Transaction from
its Category so they stay queryable on the row. Never typed directly. See ADR-0006.
_Avoid_: computed columns, denormalized tags

**Rule**:
One row of the `autocat` table: up to five conditions (`Description Contains`,
`Account Contains`, `Institution Contains`, `Amount Min`, `Amount Max`) plus the Category
it writes, with an explicit `order` and an `enabled` flag. A Rule is **active** when it is
enabled, has a Category, and declares at least one condition.
_Avoid_: pattern, filter, mapping

**Rule engine**:
`app/autocat.py`. The first active Rule in `order` whose every condition holds against a
Transaction wins; rows that predate the `order` column are numbered once from their
insertion order.
_Avoid_: categorizer

**ML model**:
`app/ml_model.py`, the sklearn pipeline under the Data directory's `models/`. Only ever
proposes; never writes `Category`.
_Avoid_: predictor, classifier

**ML suggestion**:
The ML model's top pick stored on a Transaction as `Pred:Category` / `Pred:Conf`.
Accepting one is an ordinary Category write.
_Avoid_: prediction, guess

**Rule apply**:
Writing a winning Rule's Category (plus derived fields) onto blank-Category Transactions:
in batch from the Ledger toolbar, or one row via the panel's Rule chip. The operations
where both engines meet the Ledger live in `app/categorization.py`.
_Avoid_: auto-categorize, autocat batch

## Accounts & balances

**Account**:
A row in `accounts` — a holding (asset, equity, or liability) with a current Amount.
The Accounts page renders these as cards grouped by Type.
_Avoid_: wallet, ledger account

**Snapshot**:
One dated row in `balance_history` recording an Account's Balance at a point in time.
Stamped manually, from an Account's current Amount, or by a sync; the feed keeps one per
Account per calendar day, a later run the same day replacing it. Carries two kinds: the
coarse `Type` (Assets / Liabilities / Equity, from the account-category cascade, read by the
balance sheet) and the granular `Account Type` (Checking Account, Common Stock, the Balances
grid's column). Feed and sync rows carry no `Account #`.
_Avoid_: balance record, history row, statement

**Account type preset**:
The per-launch-type bundle the Add-account form applies on save — visible fields plus
the stamped balance-sheet classification (Type/Class, Group, Category, granular
Account Type). Defined in `ACCOUNT_TYPES` (app/views/accounts.py); the user never
types classification on that form.
_Avoid_: account template, type mapping

**Linked account**:
An Account created by the type-aware Add flow whose financial truth lives in a detail
record — a portfolio holding (Common stock) or a `credit_accounts` entry (Credit card) —
sharing the card's Account ID. The card displays values derived at render and locks
type-owned fields; archive/reopen closes or restores both sides together.
_Avoid_: connected account, synced account

**Connection**:
One SimpleFIN Bridge connection (a bank login) in the `connections` table, keyed by the
Bridge's `conn_id`. Accounts point at their Connection; the Institution shown on a feed
row is the Connection's name.
_Avoid_: link, bank, institution record

**Sync run**:
One row of `sync_runs`: a feed's single pull (started, finished, status ok / partial /
failed / skipped_budget, trigger, window, counts including how many new rows a Rule
categorized and how many received an ML suggestion, provider warnings). Kept as full
history, not just the last run.
_Avoid_: sync job, import log

**Cursor**:
Where a feed's last successful window ended (`sync_cursors`: `window_end`,
`last_success_at`). The next Sync run starts an overlap behind it; it advances per chunk,
in the chunk's own commit, and never on a failed chunk.
_Avoid_: checkpoint, watermark, last sync

**Pending reconciliation**:
After a Sync run's inserts: a newly posted feed Transaction whose single pending twin
(same account, same Amount, Date within 3 days, matching description — the bank's values,
so an edited pending row still matches) is found takes the twin's Category, other
app-owned fields and Hand edits, and the twin is audited to `deletions`
(`pending_replaced`) and deleted; pending rows unseen for 7 days go the same way
(`pending_vanished`). Zero or several twins: nothing moves.
_Avoid_: dedupe, merge, cleanup

**Access URL**:
The SimpleFIN credential `https://user:pass@…/simplefin`, read-only over every linked
bank. Environment only (`SIMPLEFIN_ACCESS_URL`), claimed once from a setup token, never
stored in the database or logged. See ADR-0014.
_Avoid_: token, API key

**Setup token**:
The single-use SimpleFIN string (base64 of a claim URL) that `python -m app.simplefin.claim`
exchanges once for the Access URL. Critical until claimed, worthless after; a 403 on claim
means someone else already used it, so it is treated as compromised (`docs/SECURITY.md`).
_Avoid_: access token, API key, bridge token

**Archive (account)**:
Closing a linked Account without deleting anything: card Status and detail record flip
to Closed, active views and syncs skip them, balance history is untouched. Reopen is
the symmetric restore.
_Avoid_: soft delete, deactivate

## Inventory

**Item**:
A row in the `inventory` table — a physical thing owned, with Qty, Unit_Cost, and
Category. Rendered as cards grouped by Category; its photos are Blobs, listed in the row's
`_images`; its Documents are rows of their own.
_Avoid_: product, asset, SKU, thing

**Value** (of an Item):
`Qty × Unit_Cost`, computed for display and section totals. Not stored.
_Avoid_: worth, cost, total cost

**Document** (of an Item):
A file or note attached to one Item: a row in `documents` keyed by the parent table and row
id (ADR-0016). A `.md` or `.txt` upload is a text document, kept inline in `body` and
editable on its Document page; everything else is a file document, its bytes a Blob keyed
by the document id: a PDF or a raster image is shown in place, an HTML page in a sandboxed
frame, anything else is a download.
Listed in the Item's edit modal; deleting the Item audits and removes its Documents, leaving
their Blobs.
_Avoid_: attachment, upload, asset, file

**Note** (on an Item):
A Markdown Document written in-app: created blank from "New note", edited on its Document
page with a server-rendered live preview.
_Avoid_: comment, memo, description (that is the Notes field)

**Active inventory**:
The Items in `inventory`. Discarded items are not kept in the app database (the old
discarded-items tab lives only in the offline dump, ADR-0008). The Inventory page shows
only active.
_Avoid_: current inventory, live stock

**Clip** (an Item from a page):
Capturing an Item's fields from a live store product page via the Inventory Clipper
bookmarklet into the clip popup (`/inventory/clip`), to add a new Item or update the
one whose Link matches the page. Nothing is written until the user presses Apply.
_Avoid_: scrape, import, sync, unfurl

**Scraped value**:
A field value harvested from the product page, shown in the clip popup beside the
stored value with a checkbox. Blank stored fields are pre-ticked; conflicts are opt-in;
equal values show as "same" and cannot be ticked.
_Avoid_: remote value, fetched field, suggestion

**Search** (inventory):
Filtering the Items shown on the card board or the Column view by a typed term: up to six
words, every word a case-insensitive substring of some descriptive field or the Item_ID
(never the Link; the retailer is in Source). Client-side on the board, in the tree query on
the Column view, and in the clip picker: one rule, `app/search.py`, mirrored in
`card-editor.js`. The term rides the URL as `?q=` so a reload or a bookmark keeps it.
_Avoid_: filter (that is a status select), query, find, lookup

**Item sheet**:
The read-only one-Item page (`/inventory/{id}/sheet`): hero photo (the first stored),
thumbnails, name, brand, model, Value, a spec table of the filled descriptive fields, and
notes. Accounting-only fields (salvage, useful life, classification) are left off. It is
what the bundle's PNG captures and what the browser prints to PDF.
_Avoid_: detail page, item view, preview, listing

**Item bundle**:
The export of one Item: a zip that unpacks to `<Item_Name> (<short id>)/` holding
`item.md` (front matter with every declared field + Value + exported_at, then a body),
`card.png` (the sheet as captured in the browser) and `photos/` (stored originals,
numbered). Built on demand, never stored; a photo whose Blob is gone is skipped.
_Avoid_: export folder, archive, package, snapshot

**Kit**:
A named set of Items and Software that serve one purpose together — the home gym, the
sous-vide setup, the backup chain — with a description and how it is used, shown with the
pictures of everything in it. A Kit is a view over things already owned: it owns no Item
and no cost of its own, and it never rolls up into a report; its page shows the sum of its
members' Value and the monthly cost of its active Software. It carries a short Description,
a How-to-use text written in Markdown, its own photos (the assembled setup; the first member
photo stands in when it has none) and Documents, like an Item. A Kit has no business id: its
name is how a person knows it. See ADR-0018.
_Avoid_: group (a Category's Group field; the inventory-category Group; the card editor's
Group-by), functional group, collection, set, bundle (that is the Item bundle)

**Kit member**:
One Item or one Software that belongs to a Kit, in the order it was added. The same Item or
Software may be a member of several Kits (shared infrastructure: a network switch, a backup
subscription); an Item's edit modal and its Item sheet name the Kits it is in. Membership is
changed only on the Kit page. A membership whose Item or Software is gone is skipped, never
shown as a hole.
_Avoid_: entry, component, part, child

## Software

**Software**:
A piece of software the user has, uses, or is trialing — an app, CLI, library, editor
extension, SaaS or OS package. A distinct entity in its own `software` table and its own
board (`/software`, in the Inventory ▾ menu), reusing the card-collection module. Its
identity is a package key, it is installed on hosts, and its cost is a billing cadence.
Answers "what am I running and what does it cost me per month?"; software under
consideration and upgrade paths live in future-purchases (ADR-0017).
_Avoid_: subscription (that is one Billing_Cadence of a Software item), tool, package (a
Kind, not the entity), software item (the UI noun only)

**Status** (Software):
Where a Software item stands: `using` / `trialing` / `installed_unused` (installed
somewhere but not in use) / `cancelled` (a subscription ended) / `uninstalled` (no
Install_Location left anywhere). The default view, `active`, is the first three. A Status
is **automatic** while it equals `_import_status`, the last value the importer set; once
edited by hand the importer never changes it again.
_Avoid_: state, lifecycle (Software has no pipeline)

**Kind**:
What sort of software it is: `app` / `cli` / `library` / `extension` / `saas` /
`os_package`. A group-by option on the board. The clipper and importer set it from the
source (a registry package is a `library`, an App Store or cask entry an `app`, a formula a
`cli`); the user may reclassify — the importer fills Kind only when it is empty.
_Avoid_: type, category (that is the free-text Category)

**License_Type / Billing_Cadence**:
How the software is licensed (`free` / `oss` / `perpetual` / `subscription` / `trial`) and
how it bills (`none` / `monthly` / `yearly` / `one_time`). `Cost` is the amount per cadence
period (a `one_time` Cost is the purchase price).
_Avoid_: plan, tier, price (Cost)

**Monthly cost**:
The derived card amount and the board total: `monthly` → Cost, `yearly` → Cost ÷ 12,
nothing for one-time, none, free or oss. So the board total is the subscription run-rate.
_Avoid_: run rate (Recurring's word elsewhere), MRR

**Source_Key**:
The identity of a Software item for idempotent import and clip upserts: `source:key`, e.g.
`pacman:ripgrep`, `npm:@openai/codex`, `github:owner/repo`, `pypi:httpx`,
`appstore:904280696`, `brew:cask:visual-studio-code`. Written by the importer and the
clipper, derived from a registry Link on a hand-made card, editable so a manual card can be
linked to a registry later. Unique when present; a manual item may have none.
_Avoid_: package id, external id, slug

**SW_ID**:
The business identifier of a Software item, `SW-###`, minted by the app (max existing + 1).
Distinct from the row id.
_Avoid_: software number, item id (the Inventory word)

**Install_Location**:
One place a Software item is installed: `{host, manager, id, version, seen_at}` — e.g.
`workstation · pacman:ripgrep v15.2.0`. A Software item carries a list, one entry per host +
manager. Stored only (never a form field), shown read-only in the modal, maintained by
Import.
_Avoid_: installation, machine, device

**Facts** (Software):
The registry-owned fields the modal never writes: latest version, stars, topics, archived,
licence id, homepage, repo, bundle id, vendor, plus a Source_Key when the row had none.
Written by Import and by `POST /api/software/{id}/facts` (the clipper; a later "refresh
from source"); shown read-only in the modal. Never Status, Cost, Notes, Category or the
name.
_Avoid_: metadata, remote fields, enrichment

**Import** (Software):
Posting one host's "what is installed" run — the JSON an exporter wrote — to
`POST /api/software/import` (from the board's **Import run** strip) and upserting it on
Source_Key. A run speaks for one host and names the managers it collected; keys that host
reported before but not now lose that host's Install_Location, and flip to `uninstalled`
while their Status is still automatic. Facts the source owns are overwritten; description /
kind / vendor / category / link are filled only when empty; everything the user curates is
set on insert only. Re-posting the same run changes nothing.
_Avoid_: sync, feed (the bank word), scan

**Clip** (Software):
The Software clipper: on a GitHub, PyPI, npm, App Store or Homebrew page the registry's JSON
is fetched server-side and wins; on any other page the bookmarklet's Open Graph and
`SoftwareApplication` harvest is used. The popup finds the row by Source_Key, then by
normalised Link; ticked form fields go through the board's routes, the Facts through
`/facts`, images through fetch-image. Same popup as the Inventory Clip.
_Avoid_: scrape, fetch (the registry call), AI

**Merchant_Match**:
Reserved: the bank-statement substring (e.g. `APPLE.COM/BILL`) that will link a Software
item to Ledger rows. Stored, editable, not yet evaluated anywhere.
_Avoid_: payee, vendor (the maker, not the biller)

## Investments

**Portfolio**:
The `portfolio` table — one row per security or cash position held, with Asset, Shares,
and the last refreshed price and Current Value (REAL columns since the port). The
Investments page renders it and "Refresh prices" updates it in place.
_Avoid_: holdings table, positions, investments collection

**Holding**:
One row of the Portfolio. A Linked account of kind Common stock shares the Holding's Account
ID, and the card's value is derived from the Holding at render.
_Avoid_: position, security, stock row

## UI surfaces

**Grid**:
A server-paged AG Grid (Community Infinite Row Model) over a large table — Ledger,
Balances, Data. Each is backed by a block datasource endpoint. See ADR-0004.
_Avoid_: table, datatable, spreadsheet view

**Data page**:
The generic Grid over any app-owned table (`/data`), discovered from the live schema, for
inspecting rows that have no page of their own. Internal and credential tables are hidden;
only a table with no other editor (`autocat`) is editable there, through its Store; the
deletion log is browsable read-only for recovery.
_Avoid_: Sheets page, admin panel, raw browser

**Card editor**:
A page that renders a table as cards grouped into sections, where clicking a card
opens a modal that edits the underlying row — Accounts, Inventory, Software. A board may
offer a Group-by toggle, an in-section order of its own, and a ↗ link on each card.
_Avoid_: card view, tile page, detail panel

**Clippers page**:
`/clippers`: the one page that hands out every bookmarklet (Inventory, Software), bound to
the app origin (`CLIP_BASE_URL` or the request's). The popup each opens is one shared page
(`clip.html`), told which board it serves.
_Avoid_: bookmarklet page, setup page

**Kit page**:
`/kits` and `/kits/{id}`: a sidebar of every Kit and one Kit in detail — its cover, Description
and how-to, what it is worth, the photo grid of every Kit member, and the Transfer list that
changes membership. The Kit's own fields are edited in the card editor's modal; `/kits`
alone shows the first Kit by name.
_Avoid_: kit board (it is not a card board), kit detail, group page

**Transfer list**:
The two-list control on the Kit page: everything not in the Kit on the left (filtered by the
Search rule), the Kit's members on the right, arrows between them. Each move is saved at
once; nothing is staged.
_Avoid_: picker, dual listbox, shuttle

**Planning section**:
the Planning group of the nav and its three pages over one month's facts, each a different layout of the same
data: the Month page (`/planning/month/{YYYY-MM}`: stat tiles, Budget-vs-Actual, income
expected vs received, the Journal entry beside them), the Notebook page
(`/planning/notebook/{period}`: the entry as a document with Figure blocks, a month rail, year
reviews) and the Planner page (`/planning/planner/{YYYY}`: a year strip, the Checking forecast,
expected income, sinking funds, the entry as a drawer) and the Income page (`/planning/income`: the Income sources). Facts come from the ledger, Budgets,
Snapshots and savings goals; anything derived is labelled "estimated from ledger". See
ADR-0021.
_Avoid_: budget section (Budgets is one page it reads), dashboard, review page

**Income page**:
`/planning/income`: the Income sources as a table (name, category, cadence, amount, per
month, next date, active) with an add/edit form whose category picker lists the Income
categories, and below it the detected Recurring series no source claims, each with a "Use
this" button that prefills the form. See ADR-0022.
_Avoid_: income registry (the table is `expected_flows`; the page is the Income page), payroll
page, sources page

**Year plan page**:
`/planning/year`: twelve months starting with the current one, each with its base net
(expected income minus Recurring bills, variable spend and the savings contribution), its
Planned spend as pins with a funding bar, and the net after them, red when negative; a
detail card with "Move to" buttons that warn when the target month would go negative; an
affordability list; a strip for items dated earlier than the window; the add form; the
Sync future-purchases button. See ADR-0023.
_Avoid_: year view (the Planner's strip is the year's actuals), budget calendar, roadmap

**Projected P&L page**:
`/planning/projected`: the current month actual and eleven projected columns — income
sources, recurring bills, variable spend, one Planned row per Group, the savings
contribution, net after savings — built on the pivot helper; the P&L page itself stays
actual. Clicking a planned cell moves the item. See ADR-0023.
_Avoid_: forecast P&L, budget vs actual (that is the Budgets report), pro forma

**Calendar page**:
`/planning/calendar`: twelve month cards with net, items and flags, a shelf of Planned spend
not yet placed (click one, then a month), and a funds panel (balance now, monthly
contribution, earmarked in the window, balance by its end, short or not). See ADR-0023.
_Avoid_: wall, month grid, agenda

**Pull**:
The on-demand read of future-purchases' planned export into Expected flows: pressed, never
scheduled; open Future Purchases with a cost — researching or decided, their status shown — (recurring restocks stay in
future-purchases: small, frequent, and already in the variable spend rate); upserts by the
item's business id; a field is overwritten only when its current
value still equals what the feed last said; withdrawn items are deactivated, never deleted;
logged as a sync run with feed `future-purchases`. Off when `FUTURE_PURCHASES_URL` is unset.
See ADR-0023.
_Avoid_: sync (that is the SimpleFIN feed's word; a Pull has no schedule), import (that is
the software import run), push, webhook

**Journal entry**:
One `journal_entries` row per period — `YYYY-MM` for a month, `YYYY` for a year review —
holding a Markdown body and the figures frozen at the first save after the period has ended
(income, spend, net, net savings rate, Net worth and delta, budget version and totals, biggest
misses, the twelve-month net series) with the time they were frozen; while the period is still
open the entry shows the live figures. All three Planning pages read and write the same row;
Refreeze replaces the figures on purpose (closed periods only). Hard deletes are audited. See
ADR-0021 and its 2026-10-14 amendment.
_Avoid_: note (that is a Document on an Item), post, review (the year entry is still an
entry), comment

**Figure block**:
A server-rendered card the Notebook places inside a Journal entry's prose where the body has a
`[[figures]]` (the frozen month figures and net sparkline) or `[[misses]]` (biggest misses vs
budget) marker line; with no markers, figures go before the prose and misses after.
_Avoid_: widget, embed, pinned card, callout

**Prompt chip**:
A sentence the Planning rules derive from a month's facts (an unbudgeted group, a line over
budget three months running, a count of uncategorized rows), shown as a clickable chip that
appends the sentence to the Journal entry. A prompt is addressed when its sentence occurs in
the saved body; nothing else records it. See ADR-0021.
_Avoid_: suggestion, insight (that is the Category Insights page), nudge, todo

**Block datasource**:
The `POST` endpoint a Grid calls for one page of rows: `{startRow, endRow, sortModel, q}`
in, `{rows, lastRow}` out.
_Avoid_: pagination endpoint, data API

**Dirty-diff save**:
An edit request that carries only the fields the user actually changed, so untouched
fields are never overwritten. See ADR-0007. Values are typed columns (ADR-0012); the store
formats them for display.
_Avoid_: partial update, patch, source-typed value

## Cross-cutting

**Cashflow rollup**:
The single module (`app/rollup.py`) that aggregates `sum(Amount)` over transactions and
owns the Income/Expense classification rules — per transaction (by **Type**, never by the
sign of Amount) and per Group (`group_kinds`, by majority category Type). Reports, the
dashboard, budgets, and category-insights read through it rather than hand-rolling their
own SQL. _Avoid_: aggregation helper, stats, totals service

**Category mapping**:
A table assigning every ledger Category a role that drives one domain's rollups —
savings (`Savings_Role`) and tax (`tax_role`). The shared seed-from-ledger machinery is
`app/category_mapping.py`; each domain owns its role vocabulary and seed rule.
_Avoid_: role table, tag config, classification map

**Value parsing**:
The strict user-input coercion for manual-entry fields — money strings ("1,200", "$35")
and YYYY-MM-DD dates — lives in `app/values.py` and reports bad input as a DomainError.
The only per-caller choice is what blank means (0.0, None, or required). Lenient
display/cleaning parsers are a different contract and stay local.
_Avoid_: validation helpers, sanitizers, coercion utils

**Registry**:
A small app-authored table of manual rows (`credit_accounts`, `credit_scores`,
`credit_activity`, `tax_history`, `savings_goals`, `health_periods`) edited through the
shared machinery in `app/registry.py`: uuid-id inserts, dirty-diff updates, and audited
deletes, each domain passing its Store. Each domain owns its field vocabulary and
validation; the registry owns the CRUD.
_Avoid_: config table, lookup table, master data

**Config doc**:
One per-domain row in `metrics_config` (id = "credit", "tax", "savings"), the whole config
in its JSON column, read merged over the domain's defaults so a missing or partial doc still
works — `registry.ConfigDoc`. Domains validate their fields; the Config doc owns get/save.
_Avoid_: settings, preferences, options doc

**Chart colors**:
The six series colors every ECharts view draws from (net / top categories, income, spend,
series 4–6), chosen per user on the Dashboard's folded panel or Settings → Appearance and
kept on the Profile as overrides (`app/chart_colors.py`); each page puts them on `<html>` as
`--chart-*` tokens and `chart-theme.js` reads them from there. Not the ledger's money-in /
money-out ink.
_Avoid_: theme, palette, color scheme

**Category roster**:
The distinct set of ledger Categories, each carried with its `Group` and whether any of its
transactions is `Type=="Income"` (the seed signal). Scanned from `transactions`, not stored.
Both Category mappings seed themselves from the roster.
_Avoid_: category list, distinct categories

**Category mapping**:
A per-feature table that assigns each Category a **role** for one purpose — `Savings_Role`
(SAVINGS/INCOME/IGNORE) for the savings metrics, `tax_role` (INCOME/DEDUCTIBLE/IGNORE) plus
deduction fields for tax. One deep module (`app/category_mapping.py`) owns the shared dance —
seed from the Category roster, append-missing sync, list, and role override — and each feature
is an adapter declaring its store, role field, allowed roles, and seed rule. The reduction
of a mapping to role-sets stays in the feature that needs it.
_Avoid_: role map, tag map, category config

**Deletion audit**:
Before any hard-delete, the rows are snapshotted into the `deletions` table (with a reason
when the app, not a person, deleted them: pending_replaced, seam_replaced, feed_linked,
feed_ignored) so nothing is truly unrecoverable. See ADR-0005.
_Avoid_: soft delete, trash, recycle bin

**Store**:
The one module per entity (`app/store/<entity>.py`) that owns that entity's SQL — queries,
writes, and the aggregations over it. Views and domain modules call store functions and
never hold a statement. See ADR-0011.
_Avoid_: repository, DAO, model, table module

**Blob**:
A row in `blobs`: the bytes of one photo (of an Item, a Software row or a Kit) or of one
file Document, keyed by the photo entry id or the document id, with its content type, size
and sha256 (ADR-0020). Written in the same request as the row that names it. Kept after its
owner is deleted so a row restored from `deletions` finds its bytes; `scripts/prune_blobs.py`
removes Blobs nothing references.
_Avoid_: attachment file, upload file, photo file, GridFS

**Data directory**:
The one directory (`DATA_DIR`, default `./data`) that holds everything the app owns on disk:
`money.sqlite` (rows, photos and file Documents as Blobs) and
`models/<name>-<sha prefix>.joblib` for the categorizer. Backing up the app is copying it.
Owner-only on disk: the directory is 0700 and the database 0600, checked and fixed at every
start; a database that stays readable by other users refuses to start (`docs/SECURITY.md`).
_Avoid_: uploads folder, media root, blob store, GridFS

## Financial sections

Three distinct concepts that once shared the word "health/metrics" — now one module each,
named for the concept, not the noun.

**Data health**:
A freshness snapshot of the app's own data (`app/data_health.py`, `app_health` table):
when each section was last updated, the feed's status, and how many Transactions still need
categorizing. The Activity page renders it.
_Avoid_: app health, status, metrics

**Financial health**:
The ratio score model (`app/financial_health.py`, `health_periods` table): one period of
balance-sheet / income / cash-flow inputs in, six ratio categories plus composite 0–100 scores
out. A faithful port of the Financial Health Metrics sheet.
_Avoid_: health metrics, ratios, scoring

**Savings**:
Savings rate, goals, and projections (`app/savings.py`, `metrics_config`/`savings_goals`),
served on the Metrics page. Its **Savings rate** is Σ|SAVINGS-role categories| ÷ Σ INCOME-role
categories, classified by the savings **Category mapping** (`Savings_Role`), not by transaction
Type (the Planning pages' Net savings rate is the Type-classified figure).
_Avoid_: metrics, savings metrics

**Net worth**:
Assets plus Equity less Liabilities, from each Account's ending Snapshot in a month, computed
in one shared module (`app/networth.py`) that the Balance Sheet and the Planning section both
read. "As of a month" falls back to the latest earlier month with Snapshots and says which. See
ADR-0021.
_Avoid_: equity (one of its parts), total balance, portfolio value

**Net savings rate**:
Net ÷ income for a month, classified by the Cashflow rollup's Type rule, against the target
rate from the savings config; the figure on the Planning pages. Distinct from the Savings
page's Savings rate, which the Category mapping drives and which reads zero until roles are tagged.
_Avoid_: savings rate (unqualified), save rate, surplus ratio

**Recurring series**:
An income source or a bill found in the last two years of Transactions — grouped by Category
for income, by a normalised merchant for bills — with a cadence read off the median gap
between occurrences (weekly, biweekly, monthly, quarterly, semiyearly, yearly, else
irregular), an expected amount from the last three, a next date and a per-month amount. A
bill must also hold still: a merchant whose last three amounts spread by more than a quarter
(a gas station in a Weekly category) is variable spend, not a bill. Recomputed on every read;
never stored. See ADR-0021.
_Avoid_: subscription (that is a Software license type), scheduled transaction, rule (that is
autocat), income source table

**Expected flow**:
A row the person types (or the Pull brings in) to expect a money movement the ledger cannot
detect: a kind (income or expense), a name, the Category or Group it lands in, a cadence
(once, weekly, biweekly, semimonthly, monthly, bimonthly, quarterly, semiyearly, yearly or
irregular), an amount, the anchor date of its next occurrence (placed when it has one,
unplaced when it has none; a month-only placement is the first of the month with the day
unknown), an optional savings goal, and an origin (typed, future-purchases). Stepped by the
calendar from the anchor. One table, `expected_flows`; the Income page shows the income
rows, the Year plan the expense rows. See ADR-0023.
_Avoid_: income source (a kind of Expected flow), planned purchase (that is future-purchases'
Future Purchase), scheduled transaction, budget line

**Income source**:
An Expected flow of kind income: the Income Category it lands in, a cadence, an amount and
an anchor date. The Planning pages read the active ones first and the detected Recurring
series whose Category no source claims after them; received is always the Category's
actual income. Inactive sources are kept and ignored. See ADR-0022, ADR-0023.
_Avoid_: paycheck (one kind of source), expected income (the figure, not the row), income
stream, detected source (that is a Recurring series)

**Planned spend**:
An Expected flow of kind expense: a one-off or recurring outflow the person expects — a vet
visit, a car repair, an item decided in future-purchases — with a Group for the P&L, an
amount, a placement (a date or a month, or none while it sits on the shelf), and an
optional savings goal that funds it. A placed item subtracts from its month's base net;
inside the forecast horizon it is a dated outflow. Marking it done takes it off the plan.
See ADR-0023.
_Avoid_: wishlist, future purchase (the item in the other app; a planned spend is the
money side), commitment, bill (that is a Recurring series the detector found)

**Checking forecast**:
Ninety days of projected checking balance: the checking accounts' current Amounts, each
Recurring series projected forward, and a variable daily spend from the trailing ninety days
net of recurring bills, with its low point. An estimate shown with its assumption, never
written. See ADR-0021.
_Avoid_: cash flow projection (Savings has projections of its own), budget forecast, runway
