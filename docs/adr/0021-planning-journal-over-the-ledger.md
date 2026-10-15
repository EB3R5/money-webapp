# The Planning journal is one record per period, read through three layouts over the ledger

Decided 2026-10-05 (parent: Planning section (#140),
ticket: Docs first: ADR-0021 and glossary (#141);
design: a throwaway prototype of three layouts, kept outside the repo).

The **Planning section** (`Planning ▾`) is three pages over one month's facts: Month (figures
first), Notebook (prose with pinned figures) and Planner (a year strip, a checking forecast,
expected income, sinking funds). They exist side by side so a layout can be lived with before
one is chosen. Everything a page shows is either a fact the app already owns — Transactions,
Budgets, Snapshots, savings goals — or an estimate derived from those facts at read time and
labelled "estimated from ledger". No page invents a number the ledger cannot explain.

**One record, three layouts.** A **Journal entry** is one `journal_entries` row per period —
`YYYY-MM` for a month, `YYYY` for a year review — holding a Markdown body and the **figures
frozen at first save** (income, spend, net, net savings rate, net worth and its delta, the
budget version and totals, the biggest misses, the twelve-month net series) with the time they
were frozen. All three pages read and write that same row. The freeze is the point: a later
recategorization changes the live figures, and the entry should keep what its author was
looking at when they wrote it; a Refreeze action replaces the figures on purpose, never by
accident.

*Amended 2026-10-14.* The freeze happens at the first save **after the period has ended**, not
at the first save. While a month (or a year) is still running, its entry shows the live
figures: the October entry written on the 8th showed the 8th's spend and net worth for the
rest of the month, which is not what "what the author saw" was meant to protect. An open
period's entry has no frozen figures and no Refreeze (the action answers 409); a row frozen
while its period was still open, from before this amendment, goes back to live on its next
save and is frozen by the first save once the period has closed.

**Net worth has one owner.** The balance sheet's computation — class canonicalisation, each
account's starting / ending / maximum balance from one month's Snapshots, assets plus equity
less liabilities — moves to a shared module with an "as of month" lookup and a month-over-month
delta. The balance sheet keeps its numbers; the Planning pages read the same ones. A month with
no Snapshots falls back to the latest earlier month and says so.

**The net savings rate is net ÷ income**, classified by the Cashflow rollup's Type rule, with
the target rate from the savings config. It is not the Savings page's rate, which divides the
SAVINGS-role categories by the INCOME-role ones and reads zero until roles are tagged; both
keep their names.

**The budget for a month** is the newest saved version for that month, else the newest draft,
else none. Budget-vs-Actual rows come from the existing engine; the Planning pages add the
pick rule, not a second comparison.

**Recurring detection is a pure function, never a table.** Income sources and bills are
series found in the last two years of Transactions — grouped by Category for income, by a
normalised merchant for bills — with a cadence read off the median gap between occurrences,
the expected amount from the last three, and the next date. Every call recomputes; nothing is
stored, so nothing can drift from the ledger.

**The forecast is an estimate.** Ninety days of checking balance from the checking accounts'
current amounts, the recurring series projected forward, and a variable daily spend taken from
the trailing ninety days net of recurring bills. It is shown with its assumption and its low
point, and it is never written anywhere.

**Markdown with one textarea.** The Month and Planner pages edit the body in a plain textarea;
the Notebook renders it and has a Write mode, like a Document. A **Figure block** is rendered
by the server where the body has a `[[figures]]` or `[[misses]]` marker line, before and after
the prose when it has none. There is no contenteditable editing: one body, one editor shape.

**A prompt is addressed by its text.** A **Prompt chip** is a sentence the rules derive from the
month (an unbudgeted group, a line over budget three months running, uncategorized rows);
clicking it appends the sentence to the body, and the server counts it addressed when the
sentence occurs in the saved body. No separate state records which prompts were seen.

**Sinking funds reuse savings goals** and the progress the Savings module already derives from
them; no new fields.

**Why not a Document for the entry.** A Document needs a registered parent row to hang off,
and a period is not a row anywhere; a journal entry also carries frozen figures beside its
body, which a Document has no place for. **Why not store the recurring series.** A stored
series is a claim that goes stale the moment a Transaction is recategorized or a merchant
changes its descriptor; recomputing from the ledger keeps the estimate honest and keeps a
registry of typed expectations (a follow-up) a separate, deliberate thing.

_Consequence:_ one new table, `journal_entries`, whose hard deletes are audited (ADR-0005).
Net worth gains a single owner the balance sheet also uses. The Planning pages are
read-heavy: recurring detection and the forecast run per request, which is fine at the
ledger's size and would be the first thing to cache if it stopped being fine. A month's
frozen figures can disagree with its live ones by design; the page shows both and says when
the freeze happened.
