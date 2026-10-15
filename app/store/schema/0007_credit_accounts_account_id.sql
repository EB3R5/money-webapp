-- The Add-account fan-out links a credit Registry entry to its card by Account ID; the
-- lifecycle (archive / reopen) and the duplicate guard follow that link.
ALTER TABLE credit_accounts ADD COLUMN account_id TEXT;
