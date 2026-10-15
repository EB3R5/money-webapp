# Income sources are typed; detection fills the gaps

Decided 2026-10-05 (parent: Income sources registry (#161),
ticket: table, domain, and the Income page (#162);
follows the ADR-0021 follow-ups).

**The ledger cannot see a paycheck that is not in it.** ADR-0021 derived expected income from
Recurring series: Income-typed transactions grouped by Category, a cadence read off the gaps.
On the live ledger that finds nothing periodic — the large income lands once, the rest is
irregular — so expected income reads $0 and the Checking forecast only descends. The honest
estimate is not a useful one. An **Income source** is the fix: a row the person types with a
name, the Income category it lands in, a cadence, an amount and the next expected date.

**Typed first, detected for the rest.** The Planning pages read one merged list: every active
Income source, then every detected series whose Category no source claims, each row saying
which it is. A source therefore replaces the detector for its category rather than adding to
it, so a paycheck is never expected twice. Received stays the ledger's word: the category's
actual income in the month or the year. A source with no category expects income and
receives none, which the page shows rather than hides.

**Calendar stepping, not average days.** A detected series steps by its median gap because
that is all the ledger offers. A typed source knows its calendar: monthly means the same day
each month (clamped at month end), quarterly and yearly the same day of the month, weekly and
biweekly a fixed number of days, and semimonthly two fixed days a month — the anchor's day and
the day fifteen later — which the detector's bands cannot express and which is how many
employers pay. The anchor date is the next occurrence when the row is written; the app steps
it forward from there and never rewrites it.

**One shape for both.** A source converts to the series shape the detector produces (label,
category, cadence, amount, next date, per-month amount) plus an `origin`, so the Month page's
income table, the Planner's expected income and months, and the forecast's events consume
one list and ask the origin only when they step dates. Inactive sources are ignored
everywhere and kept for the record.

**Why not edit the categories' Timing instead.** Timing is a Category attribute the budgets
read; it says a category recurs, not how much or when. Why not a sync-side feed of pay
stubs: there is none to read. Why not store detected series and let the person edit them:
ADR-0021 keeps detection pure for a reason — a stored series drifts from the ledger — and a
typed source is a different claim, the person's, not the ledger's.

_Consequence:_ the Income page under Planning ▾ owns the rows; `app/income_sources.py` owns
the conversion, the stepping and the merge; the detector is untouched. The glossary gains
**Income source** and **Income page**. Migration 0016 adds `income_sources`; deletes are
audited (ADR-0005).
