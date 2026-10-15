-- The Sheets sync is gone (ADR-0015); its last-run row has no reader. Feed runs live in
-- sync_runs.
DROP TABLE IF EXISTS sync_state;
