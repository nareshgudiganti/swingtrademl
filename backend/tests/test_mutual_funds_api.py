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
    assert rows[0]["source"] == "manual"
    assert rows[0]["folio_number"] is None


# --------------------------------------------------------------- CAS import --


def _fake_cas_data(scheme_amfi="100033", scheme_name="Test Fund - Direct Growth"):
    from casparser.types import (
        CASData,
        CASFileType,
        FileType,
        Folio,
        InvestorInfo,
        Scheme,
        SchemeValuation,
        StatementPeriod,
        TransactionType,
    )

    scheme = Scheme(
        scheme=scheme_name,
        rta_code="RT1",
        rta="CAMS",
        isin="INF000X01ABC",
        amfi=scheme_amfi,
        open=0,
        close=100,
        close_calculated=0,
        valuation=SchemeValuation(date=date(2026, 3, 1), nav=13.0, cost=1000, value=1300),
        transactions=[
            {
                "date": date(2026, 1, 1),
                "description": "Purchase",
                "type": TransactionType.PURCHASE,
                "units": 100.0,
                "nav": 10.0,
            }
        ],
    )
    return CASData(
        statement_period=StatementPeriod(from_="2026-01-01", to="2026-03-01"),
        folios=[Folio(folio="F1", amc="Test AMC", schemes=[scheme])],
        investor_info=InvestorInfo(name="Test User", email="t@example.com", address="-", mobile="-"),
        cas_type=CASFileType.DETAILED,
        file_type=FileType.CAMS,
    )


def test_import_cas_creates_holdings_for_matched_scheme(client, db_session, monkeypatch):
    fund = _fund(db_session, scheme_code="100033", tracked=False)
    db_session.commit()

    monkeypatch.setattr(
        "swing_trade_ml.api.v1.endpoints.mutual_funds.casparser.read_cas_pdf",
        lambda *args, **kwargs: _fake_cas_data(scheme_amfi="100033"),
    )

    resp = client.post(
        "/api/v1/mutual-funds/import-cas",
        files={"file": ("cas.pdf", b"%PDF-fake", "application/pdf")},
        data={"password": "secret"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["schemes_matched"] == 1
    assert body["lots_created"] == 1
    assert body["unmatched_schemes"] == []

    holdings_resp = client.get("/api/v1/mutual-funds/holdings", headers=HEADERS)
    rows = holdings_resp.json()
    assert len(rows) == 1
    assert rows[0]["scheme_id"] == fund.id
    assert rows[0]["source"] == "cas"
    assert rows[0]["folio_number"] == "F1"


def test_import_cas_reports_unmatched_scheme_without_failing(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "swing_trade_ml.api.v1.endpoints.mutual_funds.casparser.read_cas_pdf",
        lambda *args, **kwargs: _fake_cas_data(scheme_amfi="999999", scheme_name="Unknown Fund"),
    )

    resp = client.post(
        "/api/v1/mutual-funds/import-cas",
        files={"file": ("cas.pdf", b"%PDF-fake", "application/pdf")},
        data={"password": "secret"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["schemes_matched"] == 0
    assert body["unmatched_schemes"] == ["Unknown Fund"]


def test_import_cas_rejects_a_statement_with_no_folios(client, db_session, monkeypatch):
    from casparser.types import CASData, CASFileType, FileType, InvestorInfo, StatementPeriod

    empty = CASData(
        statement_period=StatementPeriod(from_="2026-01-01", to="2026-03-01"),
        folios=[],
        investor_info=InvestorInfo(name="Test User", email="t@example.com", address="-", mobile="-"),
        cas_type=CASFileType.DETAILED,
        file_type=FileType.CAMS,
    )
    monkeypatch.setattr(
        "swing_trade_ml.api.v1.endpoints.mutual_funds.casparser.read_cas_pdf",
        lambda *args, **kwargs: empty,
    )

    resp = client.post(
        "/api/v1/mutual-funds/import-cas",
        files={"file": ("cas.pdf", b"%PDF-fake", "application/pdf")},
        data={"password": "secret"},
        headers=HEADERS,
    )

    assert resp.status_code == 422


def test_import_cas_reports_a_wrong_password_as_a_client_error(client, db_session, monkeypatch):
    def _raise(*args, **kwargs):
        raise ValueError("file has not been decrypted")

    monkeypatch.setattr(
        "swing_trade_ml.api.v1.endpoints.mutual_funds.casparser.read_cas_pdf",
        _raise,
    )

    resp = client.post(
        "/api/v1/mutual-funds/import-cas",
        files={"file": ("cas.pdf", b"%PDF-fake", "application/pdf")},
        data={"password": "wrong"},
        headers=HEADERS,
    )

    assert resp.status_code == 422
