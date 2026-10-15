"""The one Database handle (ADR-0011, sync since ADR-0024).

`database` is a module-level object every store imports. Its path comes from config at
startup; the test fixture re-points the same object at a fresh directory, so no module can
keep a stale handle (nothing copies the path, everyone holds the object).

Connections are per request or job: `acquire()` hands out the connection bound to the
current context (set by `scope()`, which the request middleware and the scheduler jobs
enter) or, outside any scope, opens one for the duration of the call. Plain `sqlite3`,
WAL journal, foreign keys on, a short busy timeout. Schema files under `schema/` are
applied in order at `init()`.

Tables whose names start with one of HIDDEN_TABLE_PREFIXES never show up in `tables()`:
SQLite's own, and the auth / session / app tables Django keeps in the same file."""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Optional

from . import permissions

log = logging.getLogger("money.store")

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
DB_FILENAME = "money.sqlite"
BUSY_TIMEOUT_MS = 5000
HIDDEN_TABLE_PREFIXES = ("sqlite_", "django_", "auth_", "money_")

_current: ContextVar[Optional[sqlite3.Connection]] = ContextVar("money_db_conn", default=None)


class Database:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir: Optional[Path] = Path(data_dir) if data_dir else None

    # --- configuration -----------------------------------------------------------

    @property
    def path(self) -> Path:
        if self.data_dir is None:
            raise RuntimeError("Database has no data_dir; call database.configure(DATA_DIR)")
        return self.data_dir / DB_FILENAME

    def configure(self, data_dir: Path) -> "Database":
        """Point the handle at a data directory. The test fixture calls this per test."""
        self.data_dir = Path(data_dir)
        return self

    # --- connections ---------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=permissions.DIR_MODE)
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        return conn

    @contextmanager
    def scope(self) -> Iterator[sqlite3.Connection]:
        """One connection for everything inside (a request, a scheduler job). Commits on a
        clean exit, rolls back on an exception, closes either way."""
        existing = _current.get()
        if existing is not None:
            yield existing
            return
        conn = self._open()
        token = _current.set(conn)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            _current.reset(token)
            conn.close()

    @contextmanager
    def acquire(self) -> Iterator[sqlite3.Connection]:
        """The connection to use right now: the scope's, or a private one for this call."""
        existing = _current.get()
        if existing is not None:
            yield existing
            return
        with self.scope() as conn:
            yield conn

    # --- schema --------------------------------------------------------------------

    def schema_files(self) -> list[tuple[int, Path]]:
        out = []
        for p in sorted(SCHEMA_DIR.glob("*.sql")):
            m = re.match(r"(\d+)_", p.name)
            if m:
                out.append((int(m.group(1)), p))
        return out

    def current_version(self, conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        if cur.fetchone() is None:
            return 0
        cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def init(self) -> int:
        """Create the data directory and apply every schema file newer than the recorded
        version. Returns the resulting version. Safe to call on every start.

        Before touching an existing database and again after creating one, the directory
        and file modes are tightened to owner-only; a database that stays readable by
        other users raises `permissions.InsecureDataDir` and the start fails."""
        self.ensure_private()
        with self.scope() as conn:
            have = self.current_version(conn)
            for version, path in self.schema_files():
                if version <= have:
                    continue
                conn.executescript(path.read_text())
                conn.execute(
                    "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(UTC).isoformat()))
                have = version
        self.ensure_private()
        return have

    def ensure_private(self) -> list[str]:
        """Owner-only modes on the data directory and database (app/store/permissions.py);
        each fix is logged, an unfixable lax mode raises."""
        fixed = permissions.ensure_private(self.path.parent, self.path)
        for line in fixed:
            log.warning("data directory permissions tightened: %s", line)
        return fixed

    def tables(self) -> list[str]:
        """Every app table, by name; the hidden prefixes (SQLite's own, Django's) left out."""
        with self.acquire() as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            return [r[0] for r in cur.fetchall()
                    if not r[0].startswith(HIDDEN_TABLE_PREFIXES)]


database = Database()
