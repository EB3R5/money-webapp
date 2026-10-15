# Expected flows: typed money movements, income and planned spend, pulled from future-purchases on demand

Decided 2026-10-05 (parent: Year plan (#167),
ticket: Docs first: ADR-0023 and glossary (#168);
design: a throwaway prototype of three layouts, kept outside the repo; follows ADR-0021 and
ADR-0022).

**One registry for expected money, both signs.** ADR-0022 gave the Planning section typed
income: an Income source with a category, a cadence, an amount and an anchor date. A vet
visit in March, a car repair in July, a laptop decided in future-purchases, a yearly
registration are the same shape with the sign flipped. Rather than a second registry that
would drift from the first, the Income sources table becomes **Expected flows**: one row per
typed money movement with a `kind` (income or expense), the cadences `once`, `bimonthly` and
`semiyearly` added, a ledger Group for the P&L to land it in, an optional savings goal, and an
`origin` (typed, or pulled from future-purchases). The Income page is one view of the table —
the income rows — and keeps its name, its form and its API.

**Placement is the anchor date.** A planned spend is placed when it has an anchor date and
unplaced when it has none; there is no second field to disagree with the first. A
month-only placement is the first of the month with `day_known` off, printed as the month.
A `once` flow occurs on its anchor and nowhere else; stepping cadences step by the calendar
as ADR-0022 set out.

**The window and the base net.** The Year plan covers twelve months starting with the
current one, so a spend planned later this month is visible. Each month starts from a base
net — expected income from the merged income sources, minus recurring bills, minus the
variable daily spend for its days, minus the savings contribution (the target rate times
expected income) — and planned spend subtracts from that. A month that goes negative is
flagged; a goal's coverage is its pooled balance plus its monthly contribution for the
months until, less what earlier items on the same goal already claim. The variable rate
already carries past lumpy spend, so a planned one-off can be counted twice; this version
subtracts nothing and labels every figure estimated. Reconciling planned spend to ledger
rows, and netting it out of the variable rate, is a follow-up.

**Pull on demand, hand edits win per field.** future-purchases is where things to buy are
researched and decided; it holds the cost, the target date and the restock cadence. The
money app does not watch it. When the person presses the button, the app reads
future-purchases' read-only planned export over the compose network, converts each decided
purchase and active recurring item to an expense flow of future-purchases origin, and
upserts by the item's business id. Each pulled row keeps a snapshot of what the feed last
said, and a field is overwritten only when its current value still equals that snapshot —
ADR-0019's rule in one column — so an amount, a month, a group or a goal the person changed
survives every later pull. An item no longer decided or active is deactivated with its
status recorded, never deleted, and comes back by the same rule. Every pull is a sync run.

**Why not a timer, a push, a shared database, a key page.** Planning happens in sittings,
so a timer would poll for nothing; a push would need the money app to accept unauthenticated
writes or grow an API-key page for one integration on one box; a shared database would
couple two schemas that have different owners. A read-only export and a button keep the
money app the only writer of its own table and make the sync visible.

**Three pages, one set of facts.** The Year plan (a timeline with a detail card and move
buttons), the Projected P&L (the current month actual and eleven projected columns, planned
spend as a row per Group) and the Calendar (month cards, a shelf of unplaced items, a funds
panel) render the same `year_plan()` facts. The existing P&L page is untouched; the
projected table is its own page built on the same pivot helper.

**Amended 2026-10-06, after the first real pull.** It brought in 34 recurring restocks and
no purchases, every one in the fallback group, and each already counted inside the variable
spend rate. The Pull now reads decided Future Purchases only — a one-off with a price and
a date is what the money app cannot know by itself — with no cost floor, since a cheap
item such as a registration is still a date worth knowing. Recurring restocks stay in
future-purchases; the export still lists them for any other reader.

**Amended again 2026-10-06, the same evening.** Decided-only brought nothing: the person
keeps every candidate in `researching` and decides at purchase time. The export now sends
every open Future Purchase with a cost, researching or decided, and the plan marks the
undecided ones; an item that leaves the pipeline still deactivates. The curation is the
cost and the date, not the status.

_Consequence:_ migration 0017 replaces `income_sources` with `expected_flows` and copies the
rows; `app/income_sources.py` becomes `app/expected_flows.py`; the forecast and the Planner
read planned spend from the same list; `FUTURE_PURCHASES_URL` unset means the pull is off.
The glossary gains Expected flow, Planned spend, Year plan page, Projected P&L page, Calendar
page and Pull; Income source becomes a kind of Expected flow.
