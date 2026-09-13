"""API tests for mutual fund holdings — see
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md §8."""

from __future__ import annotations

from datetime import date

import pytest

from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundNav

HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture(autouse=True)
def _no_real_amfi_network(monkeypatch):
    """`create_holding` seeds today's NAV via `sync_nav_snapshot(db)` (no
    `raw_text`) the first time a scheme becomes tracked, which otherwise
    makes a real HTTP call to AMFI on every test run — slow and flaky (see
    services/finance/mutual_funds.py::sync_nav_snapshot's live path). Patch
    httpx.get to return a header-only NAVAll.txt instead, matching this
    codebase's rule that tests never need network access."""

    class _FakeResponse:
        text = (
            "Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;"
            "Scheme Name;Net Asset Value;Date\n"
        )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        "swing_trade_ml.services.finance.mutual_funds.httpx.get",
        lambda *args, **kwargs: _FakeResponse(),
    )


def _fund(db_session, scheme_code="100033", name="Test Fund - Direct Growth", tracked=False):
    fund = MutualFund(scheme_code=scheme_code, name=name, category="Equity", is_tracked=tracked)
    db_session.add(fund)
    db_session.flush()
    return fund


def test_search_finds_scheme_by_name(client, db_session):
    _fund(db_session, name="Test Bluechip Fund - Direct Growth")
    db_session.commit()

    resp = client.get("/api/v1/mutual-funds/search", params={"q": "Bluechip"}, headers=HEADERS)

    assert resp.status_code == 200
    results = resp.json()
    assert any(r["name"] == "Test Bluechip Fund - Direct Growth" for r in results)


def test_add_holding_marks_scheme_tracked(client, db_session):
    fund = _fund(db_session, tracked=False)
    db_session.commit()

    resp = client.post(
        "/api/v1/mutual-funds/holdings",
        json={"scheme_id": fund.id, "units": 100.0, "purchase_nav": 40.0, "purchase_date": "2025-06-01"},
        headers=HEADERS,
    )

    assert resp.status_code == 201
    db_session.refresh(fund)
    assert fund.is_tracked is True


def test_list_holdings_includes_computed_returns(client, db_session):
    fund = _fund(db_session, tracked=True)
    db_session.add(MutualFundNav(scheme_id=fund.id, date=date(2026, 1, 1), nav=44.0))
    db_session.commit()

    create_resp = client.post(
        "/api/v1/mutual-funds/holdings",
        json={"scheme_id": fund.id, "units": 100.0, "purchase_nav": 40.0, "purchase_date": "2025-06-01"},
        headers=HEADERS,
    )
    assert create_resp.status_code == 201

    resp = client.get("/api/v1/mutual-funds/holdings", headers=HEADERS)

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["latest_nav"] == 44.0
    assert rows[0]["current_value"] == 4400.0
