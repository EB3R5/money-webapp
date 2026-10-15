# Kits are views over owned things

Decided 2026-10-03 (map: Kits — functional groups of Items and Software (#103),
ticket: Schema for Kits and Kit members (#105);
design: prototype Variant B, "Guide + transfer list").

A **Kit** is a named set of Items and Software that serve one purpose — the home gym, the
sous-vide setup, the backup chain — with a description, a how-to-use text in Markdown, its own
photos and Documents. It is a *view* over things already owned: a Kit owns no Item, has no
cost of its own, and never rolls up into the balance sheet, the Inventory Overview or any
report. Its value on its page is the sum of its members' Value and monthly cost, computed at
read time and shown nowhere else. The explicit no-s are the point: an Item's worth is counted
once, on the Item.

Membership is **many-to-many and polymorphic**: one `kit_members` table whose row names its
member as `(member_table, member_id)` — the shape `documents` and `deletions` already use for a
parent — so an Item and a Software sit in the same list, a switch can belong to two Kits, and
a third collection joins without a migration. Two typed join tables and a pair of nullable
columns were considered and rejected for the two cascades and the branching queries they cost.
There is **no SQL foreign key to the member** (SQLite cannot point one column at two tables);
deleting an Item or a Software removes its memberships in code, beside the documents cascade,
after the row is audited. The **kit side is a real foreign key** with `ON DELETE CASCADE`, like
`budget_lines → budgets`: deleting a Kit audits the Kit row with its member list and lets the
database drop the memberships. Members keep the order they were added (`position`); a
membership whose member row has gone (a partial restore) is skipped on read, never shown as a
hole.

A Kit has **no business id**: nothing imports or upserts a Kit by key, so the row id names it
in URLs and its name names it to a human. Item_ID and SW-### exist for the spreadsheet lineage
and the import identity those boards carry; a Kit carries neither.
