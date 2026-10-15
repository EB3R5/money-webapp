# SimpleFIN is a second feed; its credential lives in the environment

_Amended by ADR-0015 (2026-09-24): SimpleFIN is the only live feed; the Sheets sync it sat beside is gone._
_Amended by ADR-0019 (2026-10-03): the feed owns the provider facts until a person edits one — a hand edit on a feed Transaction is kept, per field, by every later run._

Decided 2026-09-21. SimpleFIN Bridge joins the optional Sheets import (ADR-0013) as a second
feed for connections, accounts, balances, and transactions. It is not a rewrite: the feed
writes into the existing `accounts`, `balance_history`, and `transactions` tables through
their stores, adding provider columns (`source`, `provider_account_id`, `provider_txn_id`,
`pending`, `posted_at`, `last_seen_at`; `simplefin_account_id`, `connection_id`, `currency`,
`available`, `balance_date`; `sync_run_id`) plus `connections`, `sync_runs`, and
`sync_cursors`. A feed transaction's identity is (provider account id, provider txn id),
enforced by a partial unique index; Tiller rows keep the synthetic id recipe. The feed owns
the provider facts and never overwrites app-owned fields on rows that already exist — the
same protect rule the Sheets sync follows, with the same list of Category-derived fields.
Money stays REAL (ADR-0012); the plan that proposed integer minor units targeted a fresh
repository and is not adopted here.

The Access URL (`https://user:pass@bridge.simplefin.org/simplefin`) is the read-only
credential for every linked bank. It lives only in the environment (`SIMPLEFIN_ACCESS_URL`:
`.env` now, a secrets manager later), claimed once by a CLI that prints nothing else; the
database never holds it, the client splits it into a base URL plus Basic auth so it never
enters a request URL, and a redacting log filter masks it everywhere else. A 403 from the
Bridge means revoked or compromised: unset, revoke, re-claim.

Every run writes a `sync_runs` row (full history, not just the last run) and one balance
Snapshot per account, so the Activity page and the balance sheet read the feed the way they
read the Sheets sync. Windows, the daily request budget, and pending reconciliation are
separate decisions recorded in their own slices.

_Consequence:_ the Sheets sync keeps working unchanged; a row's `source` says which feed
wrote it; anything that lists accounts or transactions sees feed rows with no code change.
