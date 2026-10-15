-- Why a row was deleted (pending_replaced, pending_vanished, …); NULL for user deletes.
ALTER TABLE deletions ADD COLUMN reason TEXT;
