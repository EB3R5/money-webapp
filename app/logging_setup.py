"""Logging with credential redaction.

RedactingFilter rewrites every record's message, args and traceback before any logger or
handler sees them: `scheme://user:pass@host` userinfo becomes `***`, the configured
SimpleFIN Access URL's credential literal is masked wherever it appears, `Authorization`
header values are blanked, and the token segment of an invitation or reset link's path is
masked (the gunicorn access log is a Python logger too). It runs from the log record factory, so a record
is redacted at creation whatever logger it was logged on and whichever handler — a server's,
a test's capture — formats it later; it is also installed on the known loggers and their
handlers for records created before configure_logging() ran. httpx itself logs at WARNING so
request URLs never reach INFO."""

from __future__ import annotations

import logging
import re
from typing import Callable, Iterable, Optional
from urllib.parse import urlsplit

_USERINFO = re.compile(r"(\b[a-z][a-z0-9+.-]*://)([^/\s@:]+)(:[^/\s@]*)?@", re.IGNORECASE)
_AUTH_HEADER = re.compile(r"(?i)(authorization\b[\s:=\"']+)(basic|bearer)?\s*[^\s,;\"']+")
# An invitation or reset link carries its token as a path segment (app/links.py); the
# access log would otherwise print an unspent link in clear.
_LINK_PATH = re.compile(r"(/(?:register|reset)/)[A-Za-z0-9_\-]{8,}")
MASK = "***"

LOGGER_NAMES = ("", "django", "django.request", "django.security", "django.server",
                "gunicorn.error", "gunicorn.access", "httpx", "httpcore", "money")


def userinfo_of(url: str) -> Optional[str]:
    """The `user:pass` literal of a URL, or None."""
    try:
        p = urlsplit(url or "")
    except ValueError:
        return None
    if not p.username:
        return None
    return f"{p.username}:{p.password}" if p.password is not None else p.username


def redact(text: str, literals: Iterable[str] = ()) -> str:
    """Mask URL userinfo, Authorization values, and any given credential literal."""
    if not isinstance(text, str) or not text:
        return text
    out = _USERINFO.sub(lambda m: f"{m.group(1)}{MASK}@", text)
    out = _AUTH_HEADER.sub(lambda m: f"{m.group(1)}{(m.group(2) + ' ') if m.group(2) else ''}{MASK}", out)
    out = _LINK_PATH.sub(lambda m: f"{m.group(1)}{MASK}", out)
    for lit in literals:
        if lit:
            out = out.replace(lit, MASK)
    return out


class RedactingFilter(logging.Filter):
    """Mutates records in place (message + args) so every downstream handler emits the
    redacted text. `get_literals` is read on every record so a credential configured after
    import (tests, a settings reload) is still masked."""

    def __init__(self, get_literals: Optional[Callable[[], Iterable[str]]] = None):
        super().__init__()
        self._get_literals = get_literals or (lambda: ())

    def filter(self, record: logging.LogRecord) -> bool:
        lits = [l for l in self._get_literals() if l]
        if isinstance(record.msg, str):
            record.msg = redact(record.msg, lits)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact(v, lits) if isinstance(v, str) else v
                               for k, v in record.args.items()}
            else:
                record.args = tuple(redact(a, lits) if isinstance(a, str) else a
                                    for a in record.args)
        # Render the traceback here, redacted, so no handler (including one attached later,
        # like a test's capture) formats the raw exception text itself.
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text, lits)
        return True


def _configured_literals() -> list[str]:
    from . import config
    lit = userinfo_of(getattr(config, "SIMPLEFIN_ACCESS_URL", ""))
    return [lit] if lit else []


_filter: Optional[RedactingFilter] = None
_factory_installed = False


def _install_record_factory(flt: RedactingFilter) -> None:
    """Every LogRecord in the process passes the filter the moment it is made."""
    global _factory_installed
    if _factory_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        flt.filter(record)
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True


def configure_logging() -> RedactingFilter:
    """Install the redaction at the record factory and on the known loggers and their
    handlers; idempotent, safe to call again after a server has attached its handlers."""
    global _filter
    if _filter is None:
        _filter = RedactingFilter(_configured_literals)
    _install_record_factory(_filter)
    for name in LOGGER_NAMES:
        lg = logging.getLogger(name)
        if _filter not in lg.filters:
            lg.addFilter(_filter)
        for h in lg.handlers:
            if _filter not in h.filters:
                h.addFilter(_filter)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return _filter
