"""SimpleFIN Bridge client.

The Access URL is `https://user:pass@bridge.simplefin.org/simplefin`. It is split once
into a base URL without userinfo plus HTTP Basic auth, so the credential never enters a
request URL, an exception, or a log line (the redaction filter is belt and braces).
Errors carry the HTTP status only, never the body. `transport` is the test seam."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Iterable, Optional
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from .models import AccountSet

ENV_VAR = "SIMPLEFIN_ACCESS_URL"


class SimpleFinError(Exception):
    """A failed Bridge call; `status` is the HTTP status (None for transport errors)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class SimpleFinAuthError(SimpleFinError):
    """403: the Access URL was revoked (or the claim token was already used)."""


class SimpleFinPaymentError(SimpleFinError):
    """402: the Bridge subscription lapsed."""


def split_access_url(access_url: str) -> tuple[str, httpx.BasicAuth]:
    """(base URL without userinfo, BasicAuth). Refuses anything but https with a credential."""
    parts = urlsplit((access_url or "").strip())
    if parts.scheme != "https":
        raise ValueError("access URL must be https")
    if not parts.username or parts.password is None:
        raise ValueError("access URL must carry user:pass@")
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    base = urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
    # Userinfo is percent-encoded on the wire; Basic auth wants the decoded credential.
    return base, httpx.BasicAuth(unquote(parts.username), unquote(parts.password))


def to_epoch(v) -> int:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return int(v.timestamp())
    if isinstance(v, date):
        return int(datetime(v.year, v.month, v.day, tzinfo=timezone.utc).timestamp())
    return int(v)


class SimpleFinClient:
    def __init__(self, access_url: str, *, timeout: float = 30.0,
                 transport: Optional[httpx.BaseTransport] = None):
        self.base_url, self._auth = split_access_url(access_url)
        self._client = httpx.Client(auth=self._auth, timeout=timeout, transport=transport,
                                    follow_redirects=False, verify=True)
        self.requests_made = 0

    def __repr__(self) -> str:
        return f"SimpleFinClient({urlsplit(self.base_url).netloc})"

    @classmethod
    def from_env(cls, **kw) -> Optional["SimpleFinClient"]:
        """The configured client, or None when SIMPLEFIN_ACCESS_URL is unset."""
        url = os.environ.get(ENV_VAR, "").strip()
        return cls(url, **kw) if url else None

    def close(self) -> None:
        self._client.close()

    def fetch_accounts(self, start=None, end=None, *, pending: bool = True,
                       balances_only: bool = False,
                       account_ids: Iterable[str] = ()) -> AccountSet:
        """GET /accounts for the window [start, end) (epoch seconds, dates, or datetimes)."""
        params: list[tuple[str, str]] = [("version", "2")]
        if start is not None:
            params.append(("start-date", str(to_epoch(start))))
        if end is not None:
            params.append(("end-date", str(to_epoch(end))))
        if pending:
            params.append(("pending", "1"))
        if balances_only:
            params.append(("balances-only", "1"))
        for a in account_ids:
            params.append(("account", str(a)))
        self.requests_made += 1
        try:
            r = self._client.get(self.base_url + "/accounts", params=params)
        except httpx.HTTPError as e:
            raise SimpleFinError(f"SimpleFIN request failed: {type(e).__name__}") from None
        if r.status_code == 403:
            raise SimpleFinAuthError("SimpleFIN access revoked (403)", 403)
        if r.status_code == 402:
            raise SimpleFinPaymentError("SimpleFIN payment required (402)", 402)
        if r.status_code >= 400:
            raise SimpleFinError(f"SimpleFIN returned HTTP {r.status_code}", r.status_code)
        try:
            body = r.json()
        except ValueError:
            raise SimpleFinError("SimpleFIN returned a non-JSON body", r.status_code) from None
        return AccountSet.model_validate(body)
