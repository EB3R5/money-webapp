"""App health / activity — one status snapshot describing how current the app's data is:
when each section was last updated, the feed's status, what date the reports are current
through, and how many transactions still need categorizing.

Computed live from the store tables, then upserted into `app_health` (id "current") so
other apps can read the latest status without recomputing (GET /api/health returns the
same snapshot, JSON-safe)."""

from calendar import monthrange
from datetime import UTC, datetime

from .simplefin import sync as simplefin
from .store import database
from .store.app_health import app_health
from .store.transactions import transactions

HEALTH_ID = "current"

# Each tracked section: its table, the timestamp columns that mark an update (max wins),
# and the optional date column that says how current its data is ("through"). A section
# with no date column reads as current through its last update. Sections flagged
# `reports` are the ones whose dates drive the top-line "reports current through".
SECTIONS = [
    {"key": "transactions", "label": "Ledger / Transactions", "table": "transactions",
     "time_cols": ["edited_at", "last_seen_at", "created_at"], "date_col": "date", "reports": True},
    {"key": "balances", "label": "Balances", "table": "balance_history",
     "time_cols": ["edited_at", "created_at"], "date_col": "date", "reports": True},
    {"key": "accounts", "label": "Accounts", "table": "accounts",
     "time_cols": ["edited_at", "last_seen_at", "created_at"]},
    {"key": "investments", "label": "Investments", "table": "portfolio",
     "time_cols": ["price_updated_at", "edited_at"]},
    {"key": "inventory", "label": "Inventory", "table": "inventory",
     "time_cols": ["edited_at", "created_at"], "date_col": "date_moved"},
    {"key": "categories", "label": "Ledger Categories", "table": "categories",
     "time_cols": ["edited_at", "created_at"]},
    {"key": "inventoryCategories", "label": "Inventory Categories", "table": "inventory_categories",
     "time_cols": ["edited_at", "created_at"]},
    {"key": "autocat", "label": "Categorization Rules", "table": "autocat",
     "time_cols": ["edited_at", "created_at"]},
    {"key": "budgets", "label": "Budgets", "table": "budgets",
     "time_cols": ["edited_at", "created_at"], "date_col": "month"},
    {"key": "software", "label": "Software", "table": "software",
     "time_cols": ["edited_at", "refreshed_at", "created_at"]},
    {"key": "kits", "label": "Kits", "table": "kits",
     "time_cols": ["edited_at", "created_at"]},
    {"key": "planning", "label": "Planning journal", "table": "journal_entries",
     "time_cols": ["edited_at", "created_at"], "date_col": "period"},
    {"key": "expectedFlows", "label": "Expected flows", "table": "expected_flows",
     "time_cols": ["edited_at", "created_at"], "date_col": "anchor_date"},
]

# Kept for the activity page's "collection" column and external readers of the snapshot.
for _s in SECTIONS:
    _s["collection"] = _s["table"]


def _as_current_date(v) -> datetime | None:
    """A date column's max → datetime for uniform display/compare. Accepts a datetime, an
    ISO "YYYY-MM-DD"-ish string, or a "YYYY-MM" month (reads as its last day — a June
    budget covers all of June); anything else is no date."""
    if isinstance(v, datetime):
        return v
    s = str(v or "").strip()
    try:
        if len(s) == 7:  # YYYY-MM
            y, m = int(s[:4]), int(s[5:7])
            return datetime(y, m, monthrange(y, m)[1])
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _as_datetime(v) -> datetime | None:
    """A timestamp column's max → naive UTC. Older rows carry naive UTC strings, rows the
    app writes carry "+00:00"; both must compare with each other and with
    the naive date columns."""
    if not isinstance(v, datetime):
        try:
            v = datetime.fromisoformat(str(v)) if v else None
        except ValueError:
            return None
    if v is not None and v.tzinfo is not None:
        v = v.astimezone(UTC).replace(tzinfo=None)
    return v


def _section_status(sec: dict) -> dict:
    q = lambda c: '"' + c + '"'  # noqa: E731
    selects = ["COUNT(*)"] + [f"MAX({q(c)})" for c in sec["time_cols"]]
    if sec.get("date_col"):
        selects.append(f"MAX({q(sec['date_col'])})")
    with database.acquire() as conn:
        cur = conn.execute(f"SELECT {', '.join(selects)} FROM {q(sec['table'])}")
        row = cur.fetchone()
    count = int(row[0])
    times = [_as_datetime(row[i + 1]) for i in range(len(sec["time_cols"]))]
    times = [t for t in times if t]
    last_updated = max(times) if times else None
    current_through = None
    if sec.get("date_col"):
        current_through = _as_current_date(row[len(sec["time_cols"]) + 1])
    return {"key": sec["key"], "label": sec["label"], "collection": sec["table"],
            "count": count, "last_updated": last_updated,
            # A section without a domain date is current through its last update.
            "current_through": current_through or last_updated}


def _needs_categorization() -> int:
    """Transactions with no Category — the count that still needs categorizing."""
    return transactions.count_blank()


def compute_health(persist: bool = True) -> dict:
    """Build the health snapshot and (by default) upsert it into app_health/current."""
    sections = [_section_status(s) for s in SECTIONS]
    # Top-line stays ledger-driven: only `reports` sections (transactions, balances) —
    # a forward-dated budget month or an edit timestamp must not move it.
    through = [s["current_through"] for spec, s in zip(SECTIONS, sections)
               if spec.get("reports") and s["current_through"]]
    snapshot = {
        "generated_at": datetime.now(UTC),
        "reports_current_through": max(through) if through else None,
        "needs_categorization": _needs_categorization(),
        "simplefin": simplefin.status(),
        "sections": sections,
    }
    if persist:
        row = {k: snapshot[k] for k in ("generated_at", "needs_categorization",
                                        "reports_current_through", "sections")}
        if app_health.get(HEALTH_ID):
            app_health.update(HEALTH_ID, row)
        else:
            app_health.insert({"_id": HEALTH_ID, **row})
    return snapshot


def jsonable(value):
    """Recursively convert datetimes to ISO strings so the snapshot is JSON-serializable."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value
