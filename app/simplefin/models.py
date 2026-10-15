"""SimpleFIN account-set models, tolerant of protocol v1 and v2.

v2 (what we ask for with version=2): errlist[{code,msg,conn_id?,account_id?}],
connections[{conn_id,name,org_id,org_url?,sfin_url}], accounts[{id,name,conn_id,currency,
balance,"available-balance"?,"balance-date",transactions[...]}]. v1 differs in three
places, lifted here before validation: errors[str] → errlist with code "gen.legacy",
a per-account org{} → a synthesized Connection, and txn payee/memo instead of extra.
Amounts are numeric strings on the wire and Decimals here; unknown keys are ignored."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LEGACY_ERROR_CODE = "gen.legacy"


def _decimal(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        d = v
    elif isinstance(v, bool):
        raise ValueError("amount must be a number")
    elif isinstance(v, (int, float)):
        d = Decimal(str(v))
    else:
        try:
            d = Decimal(str(v).strip())
        except InvalidOperation as e:
            raise ValueError(f"not a numeric amount: {v!r}") from e
    if not d.is_finite():
        raise ValueError(f"non-finite amount: {v!r}")
    return d


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ErrItem(_Base):
    code: str = LEGACY_ERROR_CODE
    msg: str = ""
    conn_id: Optional[str] = None
    account_id: Optional[str] = None


class Connection(_Base):
    conn_id: str
    name: str = ""
    org_id: Optional[str] = None
    org_url: Optional[str] = None
    sfin_url: Optional[str] = None


class Transaction(_Base):
    id: str
    posted: int
    amount: Decimal
    description: str = ""
    transacted_at: Optional[int] = None
    pending: bool = False
    extra: dict = Field(default_factory=dict)
    # v1 names, kept so a v1 payload loses nothing.
    payee: Optional[str] = None
    memo: Optional[str] = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v):
        return _decimal(v)


class Account(_Base):
    id: str
    name: str = ""
    conn_id: Optional[str] = None
    currency: str = "USD"
    balance: Decimal = Decimal("0")
    available_balance: Optional[Decimal] = Field(default=None, alias="available-balance")
    balance_date: Optional[int] = Field(default=None, alias="balance-date")
    transactions: list[Transaction] = Field(default_factory=list)

    @field_validator("balance", "available_balance", mode="before")
    @classmethod
    def _money(cls, v):
        return None if v is None else _decimal(v)


class AccountSet(_Base):
    errlist: list[ErrItem] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)
    protocol_version: int = 2

    @model_validator(mode="before")
    @classmethod
    def _lift_v1(cls, data: Any):
        """Bring a v1 body into the v2 shape: errors[str] → errlist, per-account org →
        a Connection (conn_id = org.id, else org.domain), version 1 when no connections."""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        is_v2 = "connections" in d
        if "errlist" not in d and isinstance(d.get("errors"), list):
            d["errlist"] = [{"code": LEGACY_ERROR_CODE, "msg": str(m)} for m in d["errors"]]
        conns: dict[str, dict] = {c["conn_id"]: c for c in d.get("connections") or []
                                  if isinstance(c, dict) and c.get("conn_id")}
        accounts = []
        for a in d.get("accounts") or []:
            if not isinstance(a, dict):
                continue
            a = dict(a)
            org = a.pop("org", None)
            if not a.get("conn_id") and isinstance(org, dict):
                cid = str(org.get("id") or org.get("domain") or org.get("name") or "")
                if cid:
                    a["conn_id"] = cid
                    conns.setdefault(cid, {"conn_id": cid, "name": org.get("name") or cid,
                                           "org_id": org.get("id"), "org_url": org.get("url"),
                                           "sfin_url": org.get("sfin-url") or org.get("sfin_url")})
            accounts.append(a)
        d["accounts"] = accounts
        d["connections"] = list(conns.values())
        d.setdefault("protocol_version", 2 if is_v2 else 1)
        return d
