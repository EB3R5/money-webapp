"""Data directory permissions.

The Data directory holds every transaction, every balance, and the login credential row,
so nothing on the box but the app's own user may read it: the directory is 0700, the
database file 0600, and the server process runs with umask 077 so the WAL/SHM side
files and the model file are born private (the 0700 directory is what actually
keeps a stray 0644 file inside it out of reach). `ensure_private()` runs at every
`database.init()`: a lax mode is tightened where it can be (and logged), and a database
that stays readable by others is a startup error, not a warning."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

log = logging.getLogger("money.store")

UMASK = 0o077
DIR_MODE = 0o700
FILE_MODE = 0o600
OTHERS = 0o077                       # any group/other bit set = readable by someone else
SIDE_SUFFIXES = ("-wal", "-shm", "-journal")


class InsecureDataDir(RuntimeError):
    """The database (or its directory) is readable by other users and could not be fixed."""


def apply_umask() -> int:
    """Set the process umask to 077; returns the previous value."""
    if os.name != "posix":
        return 0
    return os.umask(UMASK)


def _targets(data_dir: Path, db_path: Path) -> list[tuple[Path, int]]:
    out = [(data_dir, DIR_MODE), (db_path, FILE_MODE)]
    out += [(db_path.with_name(db_path.name + s), FILE_MODE) for s in SIDE_SUFFIXES]
    return out


def ensure_private(data_dir: Path, db_path: Path) -> list[str]:
    """Tighten the data directory and the database file (plus any WAL/SHM/journal side
    file) to owner-only. Returns one line per fix made; raises InsecureDataDir when a
    path stays readable by others (chmod refused, or a filesystem that ignores it)."""
    if os.name != "posix":
        return []
    fixed: list[str] = []
    for path, want in _targets(Path(data_dir), Path(db_path)):
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            continue
        if not mode & OTHERS:
            continue
        try:
            os.chmod(path, want)
            after = stat.S_IMODE(path.stat().st_mode)
        except OSError as e:
            raise InsecureDataDir(
                f"{path} is mode {mode:04o} (readable by other users) and could not be fixed: "
                f"{type(e).__name__}. Run `chmod {want:o} {path}` as its owner and restart.") from None
        if after & OTHERS:
            raise InsecureDataDir(
                f"{path} is still mode {after:04o} after chmod {want:o}; this filesystem does not "
                "keep permissions. Move the data directory to one that does.")
        fixed.append(f"{path.name}: {mode:04o} -> {want:04o}")
    return fixed
