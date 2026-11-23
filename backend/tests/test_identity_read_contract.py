"""Pins the identity READ contract (docs/architecture/IDENTITY-READ-API.md) that Tracks B and C code against.

Signatures, field names and the headline guarantees. No database is needed. If one of these fails, a consumer
may break: change the document and tell the lead before changing this test.
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import date

import pytest

from swing_trade_ml.db.models.identity import ScoreLedger
from swing_trade_ml.services import identity
from swing_trade_ml.services.identity import SecurityRef, consumers, get_ref, ledger, resolve
from swing_trade_ml.services.identity.memory import InMemoryStore


def _params(fn) -> dict[str, tuple[str, object]]:
    return {n: (p.kind.name, p.default) for n, p in inspect.signature(fn).parameters.items()}


def test_resolve_signature_is_pinned():
    p = _params(resolve)
    assert list(p) == ["db", "symbol", "isin", "token", "exchange", "on_date"]
    assert p["db"][0] == "POSITIONAL_OR_KEYWORD"
    for name in ("symbol", "isin", "token", "exchange", "on_date"):
        assert p[name][0] == "KEYWORD_ONLY"
    assert p["symbol"][1] is None and p["isin"][1] is None and p["token"][1] is None
    assert p["exchange"][1] == "NSE" and p["on_date"][1] is None


def test_get_ref_signature_is_pinned():
    p = _params(get_ref)
    assert list(p) == ["db", "security_id", "exchange", "on_date"]
    assert p["exchange"] == ("KEYWORD_ONLY", "NSE") and p["on_date"] == ("KEYWORD_ONLY", None)


def test_the_security_ref_fields_are_pinned():
    assert dataclasses.is_dataclass(SecurityRef)
    names = [f.name for f in dataclasses.fields(SecurityRef)]
    assert names == ["id", "isin", "name", "exchange", "symbol", "status"]
    assert SecurityRef.__dataclass_params__.frozen is True


def test_the_ledger_history_signature_is_pinned():
    p = _params(ledger.history)
    assert list(p) == ["db", "security_id", "view", "horizon_days", "source", "since", "until"]
    assert p["view"] == ("KEYWORD_ONLY", "latest")
    for name in ("horizon_days", "source", "since", "until"):
        assert p[name] == ("KEYWORD_ONLY", None)


def test_the_ledger_row_fields_a_reader_may_use_are_pinned():
    columns = {c.name for c in ScoreLedger.__table__.columns}
    promised = {
        "security_id", "session_date", "horizon_days", "source", "model_id", "model_name", "model_version",
        "score", "status", "scan_key", "revision", "supersedes_id", "input_cutoff", "scored_at", "run_ref",
        "note",
    }
    assert promised <= columns


def test_the_ledger_statuses_and_sources_are_pinned():
    from swing_trade_ml.db.models.identity import LEDGER_STATUSES, SOURCES

    assert set(LEDGER_STATUSES) == {"scored", "missing", "stale", "late", "no_score"}
    assert set(SOURCES) == {"v1_scan", "prediction", "brain", "catch_up", "backfill"}


def test_session_state_and_the_consumer_adapters_are_pinned():
    p = _params(ledger.session_state)
    assert list(p) == ["db", "security_ids", "session_date", "horizon_days", "source", "model_name"]
    assert p["horizon_days"][0] == "KEYWORD_ONLY"
    assert p["horizon_days"][1] is inspect.Parameter.empty  # required: no default
    assert p["source"] == ("KEYWORD_ONLY", None) and p["model_name"] == ("KEYWORD_ONLY", None)
    assert list(_params(consumers.security_for_instrument)) == ["db", "instrument_id"]
    p = _params(consumers.security_for_symbol)
    assert list(p) == ["db", "symbol", "on", "exchange"]
    assert p["on"] == ("KEYWORD_ONLY", None) and p["exchange"] == ("KEYWORD_ONLY", "NSE")


def test_history_refuses_an_unknown_view():
    with pytest.raises(ValueError):
        ledger.history(None, 1, view="whatever")


@pytest.fixture()
def store():
    s = InMemoryStore()
    with identity.use_store(s):
        yield s


def test_resolve_returns_none_for_doubt_and_never_writes(store):
    sid = store.add_security("INE389P01011", "Pinned Co")
    store.add_symbol(sid, "PINNED", date(2000, 1, 1))
    other = store.add_security("INE389Q01012", "Other Co")
    store.add_symbol(other, "OTHER", date(2000, 1, 1))
    before = (dict(store._securities), dict(store._aliases))
    assert resolve(None, symbol="PINNED") == sid
    assert resolve(None, symbol="NOPE") is None
    assert resolve(None, isin="not-an-isin") is None
    assert resolve(None, symbol="PINNED", isin="INE389Q01012") is None  # identifiers that disagree
    assert resolve(None) is None
    assert (dict(store._securities), dict(store._aliases)) == before


def test_the_on_date_rules_are_pinned(store):
    sid = store.add_security(None, "Dated Co")
    store.add_symbol(sid, "DATED", date(2023, 6, 1))
    store.add_instrument(sid, "DATED")
    assert resolve(None, symbol="DATED", on_date=date(2024, 1, 1)) == sid
    assert resolve(None, symbol="DATED", on_date=date(2022, 1, 1)) is None  # history exists, does not cover
    ref = get_ref(None, sid, on_date=date(2024, 1, 1))
    assert isinstance(ref, SecurityRef) and ref.symbol == "DATED" and ref.status == "active"
    assert get_ref(None, 99999) is None


def test_a_rename_keeps_the_id_for_both_symbols(store):
    sid = store.add_security(None, "Renamed Co")
    store.add_symbol(sid, "OLDSYM", date(2000, 1, 1), date(2025, 5, 31))
    store.add_symbol(sid, "NEWSYM", date(2025, 6, 1))
    assert resolve(None, symbol="OLDSYM", on_date=date(2024, 1, 1)) == sid
    assert resolve(None, symbol="NEWSYM", on_date=date(2026, 1, 1)) == sid
    assert get_ref(None, sid, on_date=date(2024, 1, 1)).symbol == "OLDSYM"
    assert get_ref(None, sid, on_date=date(2026, 1, 1)).symbol == "NEWSYM"
