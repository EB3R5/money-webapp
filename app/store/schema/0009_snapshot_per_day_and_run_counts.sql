-- One feed Snapshot per Account per calendar day (D6): a later run the same day replaces
-- that day's row. Existing feed rows are normalised to their day and de-duplicated
-- (latest run wins) before the per-day uniqueness replaces the per-run one.
UPDATE balance_history SET date = substr(date, 1, 10) || 'T00:00:00'
 WHERE source = 'simplefin' AND date IS NOT NULL;
DELETE FROM balance_history
 WHERE source = 'simplefin'
   AND rowid NOT IN (SELECT MAX(rowid) FROM balance_history WHERE source = 'simplefin'
                     GROUP BY account_id, date);
DROP INDEX IF EXISTS ux_balance_history_run;
CREATE UNIQUE INDEX ux_balance_history_feed_day ON balance_history(account_id, date)
 WHERE source = 'simplefin';

-- The sync categorizes what it inserts (D7): how many rows a Rule categorized and how many
-- received an ML suggestion, per run.
ALTER TABLE sync_runs ADD COLUMN rules_applied INTEGER;
ALTER TABLE sync_runs ADD COLUMN ml_suggested INTEGER;
