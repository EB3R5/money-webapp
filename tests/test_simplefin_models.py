"""SimpleFIN account-set models (app/simplefin/models.py): v2 parses with its hyphenated
aliases, v1 is lifted into the v2 shape, unknown keys are ignored, amounts are Decimals."""

from decimal import Decimal

import pytest

from app.simplefin.models import LEGACY_ERROR_CODE, AccountSet

V2 = {
    "errlist": [{"code": "con.refresh", "msg": "Bank is refreshing", "conn_id": "c1"}],
    "connections": [{"conn_id": "c1", "name": "Demo Bank", "org_id": "demo", "sfin_url": "https://x/sfin"}],
    "accounts": [{
        "id": "a1", "name": "Checking", "conn_id": "c1", "currency": "USD",
        "balance": "1234.56", "available-balance": "1200.00", "balance-date": 1758400000,
        "surprise": {"x": 1},
        "transactions": [
            {"id": "t1", "posted": 1758300000, "amount": "-4.50", "description": "Coffee", "pending": True,
             "extra": {"category": "food"}, "unknown": 1},
            {"id": "t2", "posted": 1758200000, "amount": "2000", "description": "Pay", "transacted_at": 1758190000},
        ],
    }],
}

V1 = {
    "errors": ["Bank needs attention"],
    "accounts": [{
        "org": {"domain": "demo.example", "name": "Demo Bank", "url": "https://demo.example",
                "sfin-url": "https://demo.example/sfin"},
        "id": "a1", "name": "Savings", "currency": "USD", "balance": "10.00", "balance-date": 1,
        "transactions": [{"id": "t9", "posted": 5, "amount": "1.00", "payee": "Someone", "memo": "hi"}],
    }],
}


def test_v2_parses_with_aliases_and_ignores_unknown_keys():
    s = AccountSet.model_validate(V2)
    assert s.protocol_version == 2
    assert s.errlist[0].code == "con.refresh" and s.errlist[0].conn_id == "c1"
    assert s.connections[0].conn_id == "c1" and s.connections[0].name == "Demo Bank"
    a = s.accounts[0]
    assert a.balance == Decimal("1234.56") and a.available_balance == Decimal("1200.00")
    assert a.balance_date == 1758400000 and not hasattr(a, "surprise")
    t1, t2 = a.transactions
    assert t1.amount == Decimal("-4.50") and t1.pending is True and t1.extra == {"category": "food"}
    assert t2.pending is False and t2.transacted_at == 1758190000


def test_v1_is_lifted_into_the_v2_shape():
    s = AccountSet.model_validate(V1)
    assert s.protocol_version == 1
    assert [e.code for e in s.errlist] == [LEGACY_ERROR_CODE]
    assert s.errlist[0].msg == "Bank needs attention"
    assert len(s.connections) == 1
    c = s.connections[0]
    assert c.conn_id == "demo.example" and c.name == "Demo Bank" and c.sfin_url == "https://demo.example/sfin"
    a = s.accounts[0]
    assert a.conn_id == "demo.example"
    assert a.transactions[0].payee == "Someone" and a.transactions[0].memo == "hi"


def test_amounts_reject_non_numeric_and_non_finite():
    for bad in ("NaN", "Infinity", "abc", True):
        with pytest.raises(ValueError):
            AccountSet.model_validate({"accounts": [{"id": "a", "balance": bad}]})
    with pytest.raises(ValueError):
        AccountSet.model_validate({"accounts": [{"id": "a", "transactions": [{"id": "t", "posted": 1, "amount": "nan"}]}]})


def test_empty_and_minimal_bodies():
    assert AccountSet.model_validate({}).accounts == []
    s = AccountSet.model_validate({"accounts": [{"id": "only"}]})
    assert s.accounts[0].balance == Decimal("0") and s.accounts[0].transactions == []
