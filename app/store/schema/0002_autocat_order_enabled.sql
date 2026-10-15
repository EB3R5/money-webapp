-- Rules carry an explicit first-match-wins order and an enabled flag (categorization
-- plan, 2026-09-21). `order` is backfilled lazily by the Rule engine from insertion order
-- the first time it finds rows without one; a missing `enabled` reads as true.
ALTER TABLE autocat ADD COLUMN "order" INTEGER;
ALTER TABLE autocat ADD COLUMN enabled INTEGER;
CREATE INDEX ix_autocat_order ON autocat("order");
