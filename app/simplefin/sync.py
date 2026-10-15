"""SimpleFIN sync run — pull one window of the account set and write it through the stores.

A second, optional feed beside the Sheets import (ADR-0013, ADR-0014): the feed owns the
provider facts until a person edits one (ADR-0019), and never overwrites app-owned fields on
rows that already exist.

  Connections  upsert on conn_id.
  Accounts     upsert on the SimpleFIN account id. Provider-owned: Amount, Institution,
               currency, available, balance_date, last_seen_at. A bank account seen for
               the first time becomes a hidden Unlinked placeholder (app/simplefin/link.py:
               a person links it to a card, promotes it, or ignores it); an ignored
               account's transactions and Snapshots are skipped.
  Transactions upsert on (provider account id, provider txn id) → a deterministic row id.
               Provider columns only; the Category-derived fields (TXN_PROTECT, the same
               list the Sheets sync protects) are never in the update. Each row keeps the
               feed's last-applied values (`_provider`, ADR-0019): a field is written only
               when the bank changed it AND the person has not — a hand edit on the Ledger
               wins for good. `updated` counts only when a stored value actually changed.
  Snapshots    one balance_history row per Account per calendar day (D6): a later run the
               same day replaces that day's Balance, available, and sync_run_id.
  Categorize   after each chunk's inserts the Rule engine batch runs on the new rows, then
               the ML suggest batch on those still blank (D7) — the same engines as the
               Ledger's buttons; the run records how many rows each touched.
  Sync run     one sync_runs row per run, running → ok | partial | failed; the cursor
               advances on success.

Windows: the Cursor says where the last successful window ended; the next run starts an
overlap behind it (first run: the initial lookback) and fetches contiguous chunks of at
most SIMPLEFIN_MAX_WINDOW_DAYS, ends exclusive, each applied and committed — cursor
included — on its own. A daily request budget (today's requests_used across sync_runs)
caps how many chunks a run may spend; none left → skipped_budget. 402/403 abort the run
as failed (earlier chunks stay); any other chunk failure or a provider con./act. warning
marks it partial and the run continues. Dry run reads and reports but writes nothing (no
run row either). With the Access URL unset the run is a no-op with one warning. After each
chunk's inserts, pending rows are reconciled (app/simplefin/pending.py).

CLI: python -m app.simplefin.sync [--dry-run] [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from .. import categorization, config
from ..logging_setup import redact
from ..store import database
from ..store.accounts import accounts
from ..store.balance_history import balance_history
from ..store.connections import connections
from ..store.sync_cursors import sync_cursors
from ..store.sync_runs import sync_runs
from ..store.transactions import (SNAPSHOT_FIELDS, month_of, provider_norm, provider_same,
                                  transactions)
from . import pending
from . import link
from .client import SimpleFinClient, SimpleFinAuthError, SimpleFinError, SimpleFinPaymentError
from .models import Account, AccountSet, Transaction

log = logging.getLogger("money.simplefin")

FEED = "simplefin"
ERR_MSG_LIMIT = 300

# App-owned account fields: set on insert, never touched by a later run.
ACCOUNT_PROTECT = ("Account", "Account ID", "Type", "Group", "Category", "Status",
                   "Account Type", "Account Kind", "is_hidden", "APR %", "Credit Limit",
                   "Min Payment", "Annual Fee", "Opened Date", "Usage Notes")
# App-owned transaction fields (the same list the Sheets sync protects) — never in an update.
TXN_PROTECT = ("Category", "Group", "Type", "Cashflow Type", "Budget", "Timing",
               "Categorized Date", "Pred:Category", "Pred:Conf")


class SyncSkipped(Exception):
    """The feed is not configured."""


class SyncBusy(Exception):
    """A run is already in progress; with a 24/day budget we refuse rather than queue."""


_lock = threading.Lock()
RUNNING_STALE_S = 3600          # a "running" row older than this is a crashed run, not a live one


def is_running(now: Optional[datetime] = None) -> bool:
    """A run is in progress here (the process lock) or in another process — the jobs
    container and the web container share the database but not a lock — which shows as a
    recent `sync_runs` row still marked running."""
    if _lock.locked():
        return True
    now = now or _now()
    for r in sync_runs.list({"feed": FEED, "status": "running"}, order=[("started_at", "desc")], limit=1):
        started = r.get("started_at")
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if (now - started).total_seconds() < RUNNING_STALE_S:
            return True
    return False


def _commit_now() -> None:
    """Make what the run wrote so far visible to the other process. Inside a request the
    store's scope would otherwise hold the running row until the response."""
    with database.acquire() as conn:
        conn.commit()


@dataclass
class SyncSummary:
    feed: str = FEED
    status: str = "ok"
    trigger: str = "cli"
    dry_run: bool = False
    run_id: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    chunks: int = 0                 # planned
    chunks_done: int = 0            # fetched and applied (or reported, on a dry run)
    budget: int = 0
    requests_used_today: int = 0    # before this run
    requests_used: int = 0
    accounts_seen: int = 0
    accounts_ignored: int = 0       # seen but skipped: a person ignored them
    connections_seen: int = 0
    txns_new: int = 0
    txns_updated: int = 0
    txns_hand_kept: int = 0         # rows where a bank change was skipped on a hand-edited field
    txns_pending_replaced: int = 0
    txns_pending_dropped: int = 0
    snapshots_added: int = 0        # new day rows
    snapshots_replaced: int = 0     # same-day rows refreshed by a later run
    rules_applied: int = 0
    ml_suggested: int = 0
    errlist: list = field(default_factory=list)
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


# --- helpers ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def epoch_to_datetime(v: Optional[int]) -> Optional[datetime]:
    return datetime.fromtimestamp(int(v), UTC) if v is not None else None


def epoch_to_day(v: int) -> datetime:
    """The Ledger's Date for a posted epoch: the UTC calendar day at midnight."""
    d = datetime.fromtimestamp(int(v), UTC).date()
    return datetime(d.year, d.month, d.day)


def txn_epoch(t: Transaction, now: datetime) -> tuple[int, Optional[int]]:
    """(the epoch that dates the row, the posted epoch or None). A pending transaction has
    `posted` 0 until it clears (SimpleFIN v2); it is dated by `transacted_at`, and if the
    bank gave neither, by the run. Otherwise every pending row would land on 1970-01-01."""
    if t.posted:
        return int(t.posted), int(t.posted)
    return int(t.transacted_at) if t.transacted_at else int(now.timestamp()), None


def txn_row_id(provider_account_id: str, provider_txn_id: str) -> str:
    """Deterministic row id for a feed Transaction: same provider ids → same row."""
    key = f"{provider_account_id}|{provider_txn_id}".encode("utf-8")
    return "sf_" + hashlib.sha256(key).hexdigest()[:24]


def sanitize_msg(s, limit: int = ERR_MSG_LIMIT) -> str:
    """Provider text before it is stored or shown: control characters out, whitespace
    collapsed, credentials redacted, truncated."""
    text = "".join(ch for ch in str(s or "") if ch >= " " or ch == "\t")
    text = " ".join(text.split())
    text = redact(text, [_credential_literal()])
    return text[:limit]


def _credential_literal() -> str:
    from ..logging_setup import userinfo_of
    return userinfo_of(config.SIMPLEFIN_ACCESS_URL) or ""


def _money(v: Optional[Decimal]) -> Optional[float]:
    return None if v is None else float(v)


# --- apply one account set -----------------------------------------------------------------

def apply_accountset(aset: AccountSet, *, run_id: Optional[str], summary: SyncSummary,
                           now: Optional[datetime] = None, window: Optional["Window"] = None) -> None:
    """Upsert connections, accounts, transactions, and one Snapshot per Account per day,
    reconcile pending rows (app/simplefin/pending.py) inside `window` when given, then
    categorize the rows this chunk inserted (Rules, then ML suggestions)."""
    now = now or _now()
    inserted_ids: list[str] = []
    conn_names: dict[str, str] = {}
    for c in aset.connections:
        conn_names[c.conn_id] = c.name or c.conn_id
        existing = connections.get(c.conn_id)
        row = {"conn_id": c.conn_id, "name": c.name or c.conn_id, "org_id": c.org_id,
               "org_url": c.org_url, "sfin_url": c.sfin_url, "last_seen_at": now}
        if existing:
            connections.update(c.conn_id, row)
        else:
            connections.insert({"_id": c.conn_id, **row})
    summary.connections_seen = len(aset.connections)

    for a in aset.accounts:
        acct_row = _upsert_account(a, conn_names.get(a.conn_id or "", a.conn_id or ""), now)
        summary.accounts_seen += 1
        if link.is_ignored(acct_row):
            summary.accounts_ignored += 1
            continue
        inserted_posted = []
        for t in a.transactions:
            new = _upsert_transaction(t, a, acct_row, now, summary)
            if new is True:
                summary.txns_new += 1
                inserted_ids.append(txn_row_id(a.id, t.id))
                if not t.pending:
                    inserted_posted.append(transactions.get(txn_row_id(a.id, t.id)))
            elif new is False:
                summary.txns_updated += 1
        summary.txns_pending_replaced += pending.reconcile_inserted(inserted_posted)
        if window is not None:
            summary.txns_pending_dropped += pending.drop_vanished(
                a.id, window_start=window.start, window_end=window.end, now=now)
        if run_id:
            outcome = _snapshot(a, acct_row, run_id, now)
            if outcome == "added":
                summary.snapshots_added += 1
            elif outcome == "replaced":
                summary.snapshots_replaced += 1
    if inserted_ids:
        summary.rules_applied += (categorization.apply_rules(ids=inserted_ids))["applied"]
        summary.ml_suggested += (categorization.suggest_batch(ids=inserted_ids))["suggested"]


def _upsert_account(a: Account, institution: str, now: datetime) -> dict:
    provider = {
        "Amount": _money(a.balance), "Institution": institution or None,
        "currency": a.currency, "available": _money(a.available_balance),
        "balance_date": epoch_to_datetime(a.balance_date), "last_seen_at": now,
        "simplefin_account_id": a.id, "connection_id": a.conn_id,
    }
    existing = accounts.one({"simplefin_account_id": a.id})
    if existing:
        accounts.update(existing["_id"], provider)
        return accounts.get(existing["_id"])
    _id = accounts.insert(link.placeholder_row(a.id, a.name, provider))
    return accounts.get(_id)


def _upsert_transaction(t: Transaction, a: Account, acct_row: dict, now: datetime,
                              summary: Optional[SyncSummary] = None) -> Optional[bool]:
    """True = inserted, False = a stored value changed, None = seen but unchanged.

    The rule (ADR-0019): per provider field, compare the bank's value and the row's value
    with the feed's last-applied value (`_provider`). The bank changed it and the person did
    not → write the bank's value. The person changed it → keep the row's value, whatever the
    bank says now. The snapshot is refreshed to the bank's values and last_seen_at stamped
    every run. A row with no snapshot yet (synced before 0013) keeps every current value and
    starts its snapshot here."""
    _id = txn_row_id(a.id, t.id)
    when, posted = txn_epoch(t, now)
    posted_day = epoch_to_day(when)
    bank = {
        "Date": posted_day, "posted_at": epoch_to_datetime(posted),
        "Description": t.description or t.payee or "", "Full Description": t.description or None,
        "Amount": _money(t.amount), "Account": acct_row.get("Account"),
        "Institution": acct_row.get("Institution"),
        "pending": bool(t.pending),
        "Metadata": json.dumps(t.extra, sort_keys=True) if t.extra else (t.memo or None),
    }
    snap_new = {f: provider_norm(f, bank[f]) for f in SNAPSHOT_FIELDS}
    current = transactions.get(_id)
    if current is None:
        transactions.insert({"_id": _id, **bank, "Month": month_of(posted_day), "source": FEED,
                                   "provider_account_id": a.id, "provider_txn_id": t.id,
                                   "last_seen_at": now, "_provider": snap_new})
        return True
    snap_old = current.get("_provider")
    updates: dict = {}
    kept = False
    if isinstance(snap_old, dict):
        for f in SNAPSHOT_FIELDS:
            row_v = provider_norm(f, current.get(f))
            hand_edited = not provider_same(f, row_v, snap_old.get(f))
            bank_changed = not provider_same(f, snap_new[f], snap_old.get(f))
            if not bank_changed:
                continue
            if hand_edited:
                kept = True                       # the person's value stays, whatever the bank says
            elif not provider_same(f, row_v, snap_new[f]):
                updates[f] = bank[f]
    effective_date = updates.get("Date", current.get("Date"))
    month = month_of(effective_date)
    if month is not None and not provider_same("Month", provider_norm("Month", current.get("Month")),
                                               provider_norm("Month", month)):
        updates["Month"] = month
    transactions.update(_id, {**updates, "_provider": snap_new, "last_seen_at": now})
    if kept and summary is not None:
        summary.txns_hand_kept += 1
    return False if updates else None


def _snapshot(a: Account, acct_row: dict, run_id: str, now: datetime) -> Optional[str]:
    """One Snapshot per Account per calendar day (the day of the provider's balance date,
    else today): "added" for a new day, "replaced" when this run refreshes today's row,
    None when this run already wrote it."""
    when = epoch_to_datetime(a.balance_date) or now
    day = datetime(when.year, when.month, when.day)
    facts = {"Balance": _money(a.balance), "available": _money(a.available_balance),
             "Account": acct_row.get("Account"), "Institution": acct_row.get("Institution"),
             "sync_run_id": run_id}
    existing = balance_history.one({"Account ID": acct_row.get("Account ID"), "Date": day, "_src": FEED})
    if existing:
        if existing.get("sync_run_id") == run_id:
            return None
        balance_history.update(existing["_id"], facts)
        return "replaced"
    balance_history.insert({
        "Account ID": acct_row.get("Account ID"), "Date": day, **facts,
        "Class": acct_row.get("Type"), "Group": acct_row.get("Group"),
        "Category": acct_row.get("Category"), "Type": acct_row.get("Type"),
        "Account Type": acct_row.get("Account Type"),
        "Month": day.strftime("%Y-%m"), "_src": FEED,
    })
    return "added"


# --- windows and budget ------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime            # exclusive

    @property
    def days(self) -> float:
        return (self.end - self.start).total_seconds() / 86400


def plan_windows(cursor_end: Optional[datetime], now: datetime, *, since: Optional[date] = None,
                 initial_lookback_days: Optional[int] = None, overlap_days: Optional[int] = None,
                 max_days: Optional[int] = None) -> list[Window]:
    """The contiguous chunks to fetch, oldest first, each at most `max_days` long, ends
    exclusive. Start = `since`, else the Cursor end minus the overlap, else now minus the
    initial lookback. Empty when there is nothing to fetch."""
    lookback = config.SIMPLEFIN_INITIAL_LOOKBACK_DAYS if initial_lookback_days is None else initial_lookback_days
    overlap = config.SIMPLEFIN_OVERLAP_DAYS if overlap_days is None else overlap_days
    span = config.SIMPLEFIN_MAX_WINDOW_DAYS if max_days is None else max_days
    if since is not None:
        start = datetime(since.year, since.month, since.day, tzinfo=UTC)
    elif cursor_end is not None:
        if cursor_end.tzinfo is None:
            cursor_end = cursor_end.replace(tzinfo=UTC)
        start = cursor_end - timedelta(days=overlap)
    else:
        start = now - timedelta(days=lookback)
    out: list[Window] = []
    while start < now:
        end = min(start + timedelta(days=span), now)
        out.append(Window(start, end))
        start = end
    return out


def requests_used_today(now: datetime) -> int:
    """Sum of requests_used over the feed's runs started today (UTC)."""
    midnight = datetime(now.year, now.month, now.day, tzinfo=UTC)
    rows = sync_runs.rows(
        "SELECT COALESCE(SUM(requests_used), 0) FROM sync_runs WHERE feed = ? AND started_at >= ?",
        [FEED, midnight.isoformat()])
    return int(rows[0][0]) if rows else 0


def budget_allows(used: int, planned: int, budget: Optional[int] = None) -> int:
    """How many of `planned` chunks today's remaining budget permits."""
    budget = config.SIMPLEFIN_DAILY_BUDGET if budget is None else budget
    return max(0, min(planned, budget - used))


# --- the run ------------------------------------------------------------------------------

def run_sync(*, trigger: str = "cli", dry_run: bool = False, since: Optional[date] = None,
                   client: Optional[SimpleFinClient] = None, now: Optional[datetime] = None,
                   budget: Optional[int] = None) -> SyncSummary:
    """Plan the windows from the Cursor, spend today's remaining budget on them in order,
    and apply each chunk in its own commit. Returns the summary that also lands in sync_runs.
    One run at a time: a second caller gets SyncBusy, never a queue."""
    if is_running(now):
        raise SyncBusy("a SimpleFIN sync is already running")
    with _lock:
        return _run_sync(trigger=trigger, dry_run=dry_run, since=since, client=client,
                               now=now, budget=budget)


def status(now: Optional[datetime] = None) -> dict:
    """What the Activity page and GET /sync/simplefin/status show."""
    now = now or _now()
    last = sync_runs.recent(FEED, limit=1)
    return {
        "configured": bool(config.SIMPLEFIN_ACCESS_URL),
        "running": is_running(now),
        "last_run": last[0] if last else None,
        "cursor": sync_cursors.get(FEED),
        "requests_used_today": requests_used_today(now),
        "budget": config.SIMPLEFIN_DAILY_BUDGET,
    }


def _run_sync(*, trigger: str, dry_run: bool, since: Optional[date],
                    client: Optional[SimpleFinClient], now: Optional[datetime],
                    budget: Optional[int]) -> SyncSummary:
    now = now or _now()
    summary = SyncSummary(trigger=trigger, dry_run=dry_run)
    if client is None:
        if not config.SIMPLEFIN_ACCESS_URL:
            log.warning("SimpleFIN sync skipped: SIMPLEFIN_ACCESS_URL is not set")
            summary.status = "skipped_unconfigured"
            return summary
        client = SimpleFinClient(config.SIMPLEFIN_ACCESS_URL)

    cursor = sync_cursors.get(FEED)
    windows = plan_windows(cursor.get("window_end") if cursor else None, now, since=since)
    summary.chunks = len(windows)
    if windows:
        summary.window_start, summary.window_end = _iso(windows[0].start), _iso(windows[-1].end)
    summary.budget = config.SIMPLEFIN_DAILY_BUDGET if budget is None else budget
    summary.requests_used_today = requests_used_today(now)
    allowed = budget_allows(summary.requests_used_today, len(windows), summary.budget)
    if windows and allowed == 0:
        summary.status = "skipped_budget"
        summary.error = (f"daily request budget spent ({summary.requests_used_today}/{summary.budget}); "
                         f"{len(windows)} chunk(s) waiting")
        log.warning("SimpleFIN sync skipped: %s", summary.error)
    windows = windows[:allowed]

    run_id = None
    if not dry_run:
        run_id = "run_" + uuid.uuid4().hex[:16]
        sync_runs.insert({"_id": run_id, "feed": FEED, "started_at": now, "status": "running",
                                "trigger": trigger, "window_start": windows[0].start if windows else None,
                                "window_end": windows[-1].end if windows else None,
                                "chunks": len(windows), "requests_used": 0})
        _commit_now()
        summary.run_id = run_id
    if summary.status == "skipped_budget":
        _finish(run_id, summary)
        return summary

    try:
        for w in windows:
            try:
                aset = client.fetch_accounts(w.start, w.end, pending=True)
            except (SimpleFinAuthError, SimpleFinPaymentError) as e:
                # Revoked or unpaid: nothing further will succeed. Earlier chunks stay committed.
                summary.status, summary.error = "failed", sanitize_msg(str(e))
                break
            except SimpleFinError as e:
                summary.status = "partial"
                summary.error = sanitize_msg(str(e))
                log.warning("SimpleFIN chunk %s→%s failed: %s", w.start.date(), w.end.date(), summary.error)
                continue
            finally:
                summary.requests_used = client.requests_made
            for e in aset.errlist:
                summary.errlist.append({"code": e.code, "msg": sanitize_msg(e.msg),
                                        "conn_id": e.conn_id, "account_id": e.account_id})
                if e.code.startswith(("con.", "act.")) and summary.status == "ok":
                    summary.status = "partial"
            if dry_run:  # report what the window holds, touch nothing
                summary.accounts_seen = len(aset.accounts)
                summary.connections_seen = len(aset.connections)
                summary.txns_new += sum(len(a.transactions) for a in aset.accounts)
                summary.chunks_done += 1
                continue
            with database.scope():        # one commit per chunk, cursor included
                apply_accountset(aset, run_id=run_id, summary=summary, now=now, window=w)
                _advance_cursor(w.end, now)
                sync_runs.update(run_id, {"requests_used": summary.requests_used})
            summary.chunks_done += 1
    except Exception as e:  # anything else: record it, never lose the run row
        summary.status, summary.error = "failed", sanitize_msg(f"{type(e).__name__}: {e}")
        log.exception("SimpleFIN sync failed")
    finally:
        _finish(run_id, summary)
    if summary.status in ("ok", "partial") and not dry_run:
        _reconcile_planned()                       # new rows may settle a planned spend (#181)
    return summary


def _reconcile_planned() -> None:
    """Best effort after a sync: a planned spend whose transaction just arrived is marked
    done. Never fails the sync."""
    try:
        from .. import reconcile
        with database.scope():
            reconcile.reconcile()
    except Exception:  # noqa: BLE001
        log.exception("reconciliation after sync failed")


def _finish(run_id: Optional[str], summary: SyncSummary) -> None:
    if not run_id:
        return
    sync_runs.update(run_id, {
        "finished_at": _now(), "status": summary.status, "chunks": summary.chunks_done,
        "requests_used": summary.requests_used, "accounts_seen": summary.accounts_seen,
        "txns_new": summary.txns_new, "txns_updated": summary.txns_updated,
        "txns_pending_replaced": summary.txns_pending_replaced,
        "txns_pending_dropped": summary.txns_pending_dropped,
        "snapshots_added": summary.snapshots_added,
        "rules_applied": summary.rules_applied, "ml_suggested": summary.ml_suggested,
        "errlist": summary.errlist, "error": summary.error})


def _advance_cursor(window_end: datetime, now: datetime) -> None:
    row = {"window_end": window_end, "last_success_at": now}
    if sync_cursors.get(FEED):
        sync_cursors.update(FEED, row)
    else:
        sync_cursors.insert({"_id": FEED, **row})


# --- CLI ------------------------------------------------------------------------------------

def format_summary(s: SyncSummary) -> str:
    lines = [f"simplefin sync: {s.status}" + (" (dry run)" if s.dry_run else ""),
             f"  window     {s.window_start} → {s.window_end}  ({s.chunks_done}/{s.chunks} chunks)",
             f"  requests   {s.requests_used}  (today before run: {s.requests_used_today}/{s.budget})",
             f"  connections {s.connections_seen}  accounts {s.accounts_seen}  ignored {s.accounts_ignored}",
             f"  transactions new {s.txns_new}  updated {s.txns_updated}  hand edits kept {s.txns_hand_kept}  "
             f"pending replaced {s.txns_pending_replaced}  dropped {s.txns_pending_dropped}",
             f"  snapshots  {s.snapshots_added} new  {s.snapshots_replaced} refreshed",
             f"  categorized by rules {s.rules_applied}  ML suggestions {s.ml_suggested}"]
    for e in s.errlist:
        lines.append(f"  warning    [{e['code']}] {e['msg']}")
    if s.error:
        lines.append(f"  error      {s.error}")
    return "\n".join(lines)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.simplefin.sync")
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="window start (default: 90 days ago)")
    args = ap.parse_args(argv)
    since = date.fromisoformat(args.since) if args.since else None
    database.configure(config.DATA_DIR)
    database.init()
    s = run_sync(trigger="cli", dry_run=args.dry_run, since=since)
    print(format_summary(s))
    return 0 if s.status in ("ok", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
