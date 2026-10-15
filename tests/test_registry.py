"""Registry — the shared Config doc + registry CRUD machinery. The behaviour the domains
inherit for free: deletes snapshot to the `deletions` audit log (ADR-0005) and updates
$set only the fields sent (ADR-0007)."""

import pytest

from app import credit, savings
from app.web import DomainError
from app.store.credit_accounts import credit_accounts
from app.store.deletions import deletions


def test_registry_delete_is_audited(store_client):
    credit.add_account({"name": "Card A", "credit_limit": 1000})
    acct_id = (credit.list_accounts())[0]["id"]
    credit.delete_account({"id": acct_id})

    assert credit_accounts.get(acct_id) is None
    snap = deletions.one({"collection": "credit_accounts"})
    assert snap and snap["doc"]["name"] == "Card A"
    assert snap["doc"]["credit_limit"] == 1000.0


def test_registry_update_is_dirty_diff(store_client):
    # Editing one field must never blank an untouched one (the ADR-0007 bug class).
    credit.add_account({"name": "Card A", "credit_limit": 1000, "apr": 24.9,
                              "notes": "keep me"})
    acct_id = (credit.list_accounts())[0]["id"]
    credit.update_account({"id": acct_id, "credit_limit": 2000})

    acct = (credit.list_accounts())[0]
    assert acct["credit_limit"] == 2000.0
    assert acct["apr"] == 0.249          # untouched
    assert acct["notes"] == "keep me"    # untouched


def test_registry_update_validates_sent_fields(store_client):
    credit.add_account({"name": "Card A"})
    acct_id = (credit.list_accounts())[0]["id"]
    with pytest.raises(DomainError):
        credit.update_account({"id": acct_id, "name": ""})
    with pytest.raises(DomainError):
        credit.update_account({"id": "nope", "name": "X"})


def test_config_doc_merges_partial_over_defaults(store_client):
    # A partial stored doc still yields every default key.
    savings.set_savings_config({"target_rate": 0.25})
    cfg = savings.get_savings_config()
    assert cfg["target_rate"] == 0.25
    assert cfg["income_override"] == 0.0
    assert cfg["scenario_rates"] == [0.10, 0.15, 0.20, 0.25, 0.30]


def test_goal_delete_is_audited(store_client):
    savings.add_goal({"name": "House", "target_amount": 10000})
    gid = (savings.list_goals(2024))[0]["id"]
    savings.delete_goal({"id": gid})
    snap = deletions.one({"collection": "savings_goals"})
    assert snap and snap["doc"]["name"] == "House"
