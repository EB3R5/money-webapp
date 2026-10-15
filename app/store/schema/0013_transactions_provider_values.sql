-- Hand edits on feed Transactions survive a Sync run (ADR-0019). `provider_values` is the
-- feed's last-applied value per provider field — JSON {field: normalized value} — so a later
-- run can tell a bank change (bank ≠ snapshot → write) from a hand edit (row ≠ snapshot →
-- keep). NULL on Tiller rows and on feed rows synced before this file: those keep their
-- current values and gain a snapshot on their next run (no backfill on purpose: a backfill
-- would turn an edit made just before the deploy into a "bank value").
ALTER TABLE transactions ADD COLUMN provider_values TEXT;
