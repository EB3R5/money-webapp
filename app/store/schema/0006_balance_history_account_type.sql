-- The Balances grid's "Account Type" column (Checking Account, Common Stock, ...) as a real
-- column. It was Tiller's duplicate-header Type__15 in the Mongo era and was stripped by
-- the export; `type` keeps the coarse category-derived meaning (Assets / Liabilities /
-- Equity) the balance sheet and the account-category cascade read.
ALTER TABLE balance_history ADD COLUMN account_type TEXT;
