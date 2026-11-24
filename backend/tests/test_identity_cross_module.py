# ruff: noqa: E501 (long lines in test code)
"""Cross-module check of the identity contract (#389, docs/architecture/IDENTITY-READ-API.md).

Every module on this base that keys by stock must name a stock only through `services/identity`: never create one
outside the writer, get None (or an error) on doubt, and read a symbol on the session it belongs to.

Two parts. STATIC: the source is parsed, so a new module that breaks a rule fails here before it runs. BEHAVIOURAL: one
check per keyed module on a real database (rolled back), using the shared fixtures in `identity_fixtures.py`.
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from identity_fixtures import FRIDAY, THURSDAY, seed_renamed_stock, seed_stale_stock
from swing_trade_ml.brain.horizons import ModelOutput, run_horizon
from swing_trade_ml.db.models.identity import ScoreLedger, Security
from swing_trade_ml.services import horizon_nightly, horizon_records, score_history
from swing_trade_ml.services.identity import consumers, resolve, writer
from swing_trade_ml.simulation import ledger as sim_ledger
from swing_trade_ml.simulation import runner, source, store
from test_p0_end_to_end import MODEL_5D, SESSIONS, world  # noqa: F401 - `world` is a fixture
from test_simulation_runner import stored  # noqa: F401 - fixture: the world's prices as stored candles

SRC = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml"
IDENTITY_PACKAGE = "services/identity/"

# Modules that key by stock today. A new one must be added HERE, with a behavioural check below: that is the review hook.
KEYED_MODULES = {
    "services/horizon_nightly.py",
    "services/horizon_records.py",
    "services/score_history.py",
    "simulation/ledger.py",
    "simulation/momentum.py",  # picks by security id; behaviour checked in test_simulation_momentum.py (ids, ties, declared universe)
    "simulation/runner.py",
    "simulation/source.py",
    "simulation/store.py",
}
# Only these may use the identity WRITER (create or change a stock). score_history seeds a security for a stock the
# first time it is scored; everything else only reads. The admin command lives inside the identity package.
# horizon_nightly links a followed stock that has no security yet through the writer's own idempotent path (and skips it on
# an identity conflict); it never builds a stock row itself.
WRITER_USERS = {"services/score_history.py", "services/horizon_nightly.py"}
# Only these may read the identity tables directly instead of through the read API. KNOWN: the simulation source lists
# every security id to read horizon records for them; it should ask the read API instead.
DIRECT_TABLE_READERS = {"db/models/__init__.py", "simulation/source.py"}


def _files():
    for path in sorted(SRC.rglob("*.py")):
        yield path.relative_to(SRC).as_posix(), ast.parse(path.read_text(encoding="utf8"))


def _outside_identity():
    return [(rel, tree) for rel, tree in _files() if not rel.startswith(IDENTITY_PACKAGE)]


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


# ------------------------------------------------------------------------------------------------ static


def test_the_keyed_modules_are_the_known_ones():
    found = {
        rel
        for rel, tree in _outside_identity()
        if not rel.startswith("db/") and any(isinstance(n, ast.Name | ast.Attribute | ast.arg | ast.keyword) and "security_id" in (getattr(n, "id", "") or getattr(n, "attr", "") or getattr(n, "arg", "") or "") for n in ast.walk(tree))
    }
    assert found == KEYED_MODULES, f"a module now keys by stock: add it to KEYED_MODULES and give it a behavioural check: {sorted(found ^ KEYED_MODULES)}"


def test_only_the_known_modules_use_the_identity_writer():
    users = {
        rel
        for rel, tree in _outside_identity()
        if any(n.startswith("swing_trade_ml.services.identity.writer") or n == "swing_trade_ml.services.identity.writer" for n in _imported_names(tree))
        or any(
            isinstance(node, ast.ImportFrom) and node.module == "swing_trade_ml.services.identity" and any(a.name == "writer" for a in node.names)
            for node in ast.walk(tree)
        )
    }
    assert users <= WRITER_USERS, f"a module creates or changes stocks outside the writer's owners: {sorted(users - WRITER_USERS)}"


def test_no_security_row_is_built_outside_the_writer():
    banned = {"Security", "SecuritySymbol", "SecurityAlias"}
    built = []
    for rel, tree in _files():
        if rel in {"services/identity/writer.py"}:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                if name in banned:
                    built.append((rel, node.lineno, name))
    assert built == [], built


def test_identity_tables_are_read_only_through_the_read_api():
    readers = {
        rel
        for rel, tree in _outside_identity()
        if any(n == "swing_trade_ml.db.models.identity" or n.startswith("swing_trade_ml.db.models.identity.") for n in _imported_names(tree))
    }
    assert readers <= DIRECT_TABLE_READERS, sorted(readers - DIRECT_TABLE_READERS)


def _symbol_lookups_without_a_date() -> set[tuple[str, str]]:
    missing: set[tuple[str, str]] = set()
    for rel, tree in _outside_identity():
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    callee = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    keywords = {k.arg for k in node.keywords}
                    if callee == "resolve" and "symbol" in keywords and "on_date" not in keywords:
                        missing.add((rel, fn.name))
    return missing


def test_every_symbol_lookup_passes_the_session_it_belongs_to():
    assert _symbol_lookups_without_a_date() == set()


# ------------------------------------------------------------------------------------------ behavioural


def _securities(db) -> int:
    return len(list(db.scalars(select(Security.id))))


def _sessions_from(day: date) -> tuple[date, ...]:
    return tuple(d for i in range(40) if (d := day + timedelta(days=i)).weekday() < 5)


def _horizon_record(symbol: str, session: date):
    out = ModelOutput(
        model_name="xmod", model_version="v1", forecast_horizon_sessions=5, role="final",
        symbol=symbol, input_session=session, input_close=100.0, score=0.9,
    )
    return run_horizon(5, [out], session, _sessions_from(session), symbol=symbol)


def test_horizon_records_never_create_a_stock_and_use_the_resolved_id(db_session):
    renamed = seed_renamed_stock(db_session)
    before = _securities(db_session)
    with pytest.raises(horizon_records.UnknownSecurityError):
        horizon_records.save_for_symbol(db_session, _horizon_record("NOSUCHXMOD", renamed.renamed_on))
    saved = horizon_records.save_for_symbol(db_session, _horizon_record(renamed.new_symbol, renamed.renamed_on))
    assert saved.created and _securities(db_session) == before
    rows = horizon_records.records_for(db_session, renamed.security_id, view="all")
    assert [r.security_id for r in rows] == [renamed.security_id]


def test_a_horizon_record_for_a_session_before_a_rename_is_kept_under_the_same_stock(db_session):
    renamed = seed_renamed_stock(db_session)
    saved = horizon_records.save_for_symbol(db_session, _horizon_record(renamed.old_symbol, renamed.last_old_day))
    assert saved.created
    assert [r.security_id for r in horizon_records.records_for(db_session, renamed.security_id, view="all")] == [renamed.security_id]


def test_the_simulation_source_resolves_on_the_session_date_and_raises_on_doubt(db_session):
    renamed = seed_renamed_stock(db_session)
    before = _securities(db_session)
    assert source.security_ids_for(db_session, [renamed.old_symbol], renamed.last_old_day) == {renamed.old_symbol: renamed.security_id}
    assert source.security_ids_for(db_session, [renamed.new_symbol], renamed.renamed_on) == {renamed.new_symbol: renamed.security_id}
    with pytest.raises(source.UnknownStockError):
        source.security_ids_for(db_session, [renamed.old_symbol], renamed.renamed_on)  # it no longer carried that symbol
    with pytest.raises(source.UnknownStockError):
        source.security_ids_for(db_session, ["NOSUCHXMOD"], FRIDAY)
    assert source.symbol_on(db_session, renamed.security_id, renamed.last_old_day) == renamed.old_symbol
    assert source.symbol_on(db_session, renamed.security_id, renamed.renamed_on) == renamed.new_symbol
    assert _securities(db_session) == before


def test_the_simulation_store_refuses_a_row_without_a_security_id():
    record = SimpleNamespace(
        rule_version="r1", cash=1.0, session="2026-11-20", fills=[SimpleNamespace(security_id=None)], exits=[], blocks=[], positions=[]
    )
    ledgers = {"p": SimpleNamespace(spec=SimpleNamespace(persona_key="p", counts_in_comparison=True), rule_version="r1", records=[record])}
    with pytest.raises(store.StoreError):
        store._validate("run", ledgers, SimpleNamespace(version="r1"))


def test_the_simulation_ledger_keys_every_record_by_security_id_with_no_default():
    import dataclasses

    for cls in (sim_ledger.Candidate, sim_ledger.FillRecord, sim_ledger.ExitRecord, sim_ledger.BlockRecord, sim_ledger.PositionMark):
        field = {f.name: f for f in dataclasses.fields(cls)}["security_id"]
        assert field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING, cls.__name__


def test_the_score_ledger_files_each_stock_under_its_own_session(db_session, monkeypatch):
    stale = seed_stale_stock(db_session)

    class Clock(score_history.datetime):
        @classmethod
        def now(cls, tz=None):
            from datetime import datetime

            from swing_trade_ml.core.market_session import IST

            fixed = datetime(2026, 11, 20, 15, 50, tzinfo=IST)
            return fixed.astimezone(tz) if tz else fixed

    monkeypatch.setattr(score_history, "datetime", Clock)
    score_history.record_stock_scores(db_session, [(stale.fresh.id, 0.8, "m:v1"), (stale.stale.id, 0.7, "m:v1")], 0.4)
    fresh_id = resolve(db_session, symbol=stale.fresh.tradingsymbol)
    stale_id = resolve(db_session, symbol=stale.stale.tradingsymbol)
    assert {r.session_date for r in db_session.scalars(select(ScoreLedger).where(ScoreLedger.security_id == fresh_id))} == {FRIDAY}
    sessions = {(r.session_date, r.status) for r in db_session.scalars(select(ScoreLedger).where(ScoreLedger.security_id == stale_id))}
    assert sessions == {(THURSDAY, "scored"), (FRIDAY, "stale")}


def test_the_consumer_adapters_follow_the_rename_and_agree_with_resolve(db_session):
    renamed = seed_renamed_stock(db_session)
    assert consumers.security_for_instrument(db_session, renamed.instrument.id) == renamed.security_id
    assert consumers.security_for_symbol(db_session, renamed.old_symbol, on=renamed.last_old_day) == renamed.security_id
    assert consumers.security_for_symbol(db_session, renamed.new_symbol, on=renamed.renamed_on) == renamed.security_id
    assert consumers.security_for_symbol(db_session, renamed.old_symbol, on=renamed.renamed_on) is None


def test_reading_never_creates_a_stock(db_session):
    renamed = seed_renamed_stock(db_session)
    before = _securities(db_session)
    for _ in range(2):
        resolve(db_session, symbol="NOSUCHXMOD")
        resolve(db_session, symbol=renamed.old_symbol, on_date=renamed.renamed_on)
        consumers.security_for_symbol(db_session, "NOSUCHXMOD")
        consumers.security_for_instrument(db_session, 99_999_999)
    assert _securities(db_session) == before
    assert writer.create_security  # the writer is the one place a stock is made


def test_the_nightly_job_links_a_new_stock_through_the_writer_and_skips_a_conflict(db_session):
    from identity_fixtures import instrument

    summary = horizon_nightly.DaySummary(FRIDAY)
    known = seed_renamed_stock(db_session)
    assert horizon_nightly._link(db_session, known.instrument, summary) is True
    assert (summary.resolved, summary.linked) == (1, 0), "a known stock is resolved, not made again"

    fresh = instrument(db_session, "NIGHTFX1", name="Night Fixture One Ltd")
    before = _securities(db_session)
    assert horizon_nightly._link(db_session, fresh, summary) is True
    assert summary.linked == 1 and _securities(db_session) == before + 1
    assert resolve(db_session, token=fresh.instrument_token) is not None

    owner = writer.create_security(db_session, name="The Original Company Ltd")
    writer.set_symbol(db_session, owner, "NIGHTCLASH", date(2000, 1, 1))
    clash = instrument(db_session, "NIGHTCLASH", name="A Different Holdings Ltd")
    assert horizon_nightly._link(db_session, clash, summary) is False
    assert summary.refused == 1
    assert resolve(db_session, token=clash.instrument_token) is None, "nothing was linked by guessing"


def test_the_simulation_runner_resolves_through_the_identity_api_creates_no_stock_and_passes_the_session(stored, monkeypatch):  # noqa: F811
    db = stored["db"]
    before = _securities(db)
    seen = {}
    real = source.bars_from_candles

    def spy(session, security_ids, sessions):
        seen["db"], seen["ids"], seen["sessions"] = session, list(security_ids), list(sessions)
        return real(session, security_ids, sessions)

    monkeypatch.setattr(source, "bars_from_candles", spy)
    universe = sorted(db.scalars(select(Security.id)))
    report = runner.run_and_persist(db, run_key="xmod-runner", sessions=SESSIONS, models=[MODEL_5D], momentum_universe=universe)
    assert report.fills > 0
    assert seen["db"] is db and seen["sessions"] == list(SESSIONS)
    known = {row for row in db.scalars(select(Security.id))}
    assert seen["ids"] and set(seen["ids"]) <= known, "the runner asked for a stock the identity layer does not know"
    assert _securities(db) == before, "the runner created or changed a stock"
