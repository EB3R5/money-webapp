"""Live check against SimpleFIN's public demo access URL. Opt in with SIMPLEFIN_DEMO=1;
skipped otherwise so the suite never needs the network."""

import os

import pytest

from app.simplefin.client import SimpleFinClient

DEMO_ACCESS_URL = "https://demo:demo@beta-bridge.simplefin.org/simplefin"

pytestmark = pytest.mark.skipif(os.environ.get("SIMPLEFIN_DEMO") != "1",
                                reason="set SIMPLEFIN_DEMO=1 to hit the public demo bridge")


def test_demo_accounts_parse():
    c = SimpleFinClient(DEMO_ACCESS_URL)
    s = c.fetch_accounts()
    assert s.accounts, "demo returned no accounts"
    for a in s.accounts:
        assert a.id and a.balance is not None
        for t in a.transactions:
            assert t.id and t.posted and t.amount is not None
    assert c.requests_made == 1
