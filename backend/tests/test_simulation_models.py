# ruff: noqa: E501  (long plain-English test text)
"""#321 the run names its model(s): several models may score one stock on one session, and the simulation never picks
between them silently. Records of models that were not named are ignored; if more than one record is left for a stock and
session the run is refused with a plain error. There is no default model.

Uses the synthetic world of the end-to-end test (identity writer -> horizon records), plus a second ("challenger") 5D
model that scores the same stocks. Needs the test database; every write rolls back with the test."""

from __future__ import annotations

import pytest

from swing_trade_ml.brain.horizons import HorizonStore, ModelOutput, run_all_horizons
from swing_trade_ml.services import horizon_records as hr
from swing_trade_ml.simulation import source
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.rules import TradingRules
from test_p0_end_to_end import ALL_DAYS, RECORDED, SESSIONS, world  # noqa: F401 - `world` is a fixture

MAIN = "synthetic_h5"  # the model the world's records were written by
CHALLENGER = "challenger_h5"


def _challenger(world, symbol, score, *, name=CHALLENGER, version="v9.1", days=RECORDED):  # noqa: F811
    for day in days:
        output = ModelOutput(
            model_name=name,
            model_version=version,
            forecast_horizon_sessions=5,
            role="final",
            symbol=symbol,
            input_session=day,
            input_close=100.0,
            score=score,
        )
        record = run_all_horizons(
            day, [output], ALL_DAYS, HorizonStore(), symbol=symbol, research_caller=True
        )[5]
        hr.save_for_symbol(world["db"], record, scan_key=f"chal:{day}", run_ref=f"chal-{day}")
    world["db"].flush()


def _ids(decisions):
    return {c.record_id for picks in decisions.values() for c in picks}


def _picks(db, rules, models, policy=Policy.MODEL_ONLY):
    return source.decisions_from_horizon_records(db, rules, policy, models=models)


def test_there_is_no_default_model_and_an_empty_list_is_refused(world):  # noqa: F811
    db, rules = world["db"], TradingRules.plan_5d()
    with pytest.raises(TypeError):
        source.decisions_from_horizon_records(db, rules, Policy.MODEL_ONLY)
    with pytest.raises(TypeError):
        source.decisions_by_policy(db, rules)
    for empty in ((), [], [""], ["  "]):
        with pytest.raises(source.ModelNotNamedError):
            _picks(db, rules, empty)
    with pytest.raises(source.ModelNotNamedError):
        source.read_records(db, rules, models=None)


def test_two_models_scoring_one_stock_use_only_the_named_models_record(world):  # noqa: F811
    db, rules = world["db"], TradingRules.plan_5d()
    baseline = _picks(db, rules, [MAIN])
    stock = next(
        sid for sid, symbol in world["secs"].items() if symbol == "P0E5"
    )  # the main model says WAIT (0.30)
    _challenger(world, "P0E5", 0.99)
    # naming the main model: the challenger is ignored, nothing changes
    assert _picks(db, rules, [MAIN]) == baseline
    assert all(c.security_id != stock for picks in baseline.values() for c in picks)
    # naming the challenger: only its records are used, and only for the stock it scored
    only = _picks(db, rules, [CHALLENGER])
    assert {c.security_id for picks in only.values() for c in picks} == {stock}
    challenger_ids = {r.id for r in source.read_records(db, rules, models=[CHALLENGER])}
    assert _ids(only) == challenger_ids and len(challenger_ids) == len(RECORDED)
    assert not _ids(only) & _ids(baseline)


def test_two_named_models_with_a_record_for_one_stock_and_session_refuse_the_run(world):  # noqa: F811
    db, rules = world["db"], TradingRules.plan_5d()
    _challenger(world, "P0E5", 0.99)
    for policy in (Policy.MODEL_ONLY, Policy.BRAIN_FILTERED):
        with pytest.raises(source.AmbiguousRecordsError) as caught:
            _picks(db, rules, [MAIN, CHALLENGER], policy)
        text = str(caught.value)
        assert "P0E5" in text or str(next(s for s, n in world["secs"].items() if n == "P0E5")) in text
        assert MAIN in text and CHALLENGER in text and "name one model" in text
    with pytest.raises(source.AmbiguousRecordsError):
        source.decisions_by_policy(db, rules, models=[MAIN, CHALLENGER], sessions=SESSIONS)
    # two models that never share a stock and session are fine
    assert _picks(db, rules, [MAIN, "never_wrote_anything"])


def test_two_versions_of_one_model_are_ambiguous_until_the_version_is_named(world):  # noqa: F811
    db, rules = world["db"], TradingRules.plan_5d()
    _challenger(world, "P0E5", 0.99, version="v9.1")
    _challenger(world, "P0E5", 0.95, version="v9.2")
    with pytest.raises(source.AmbiguousRecordsError, match=r"v9.1"):
        _picks(db, rules, [CHALLENGER])
    first = _picks(db, rules, [source.ModelRef(CHALLENGER, "v9.1")])
    second = _picks(db, rules, [source.ModelRef(CHALLENGER, "v9.2")])
    assert _ids(first) and _ids(second) and not _ids(first) & _ids(second)
    assert {c.score for picks in first.values() for c in picks} == {0.99}


def test_the_wasted_buy_slot_cannot_happen_two_records_never_become_two_picks(world):  # noqa: F811
    db, rules = world["db"], TradingRules.plan_5d()
    stock = next(
        sid for sid, symbol in world["secs"].items() if symbol == "P0E0"
    )  # the main model says TRADE (0.90)
    _challenger(world, "P0E0", 0.97)
    with pytest.raises(source.AmbiguousRecordsError):
        _picks(db, rules, [MAIN, CHALLENGER])
    for model in (MAIN, CHALLENGER):
        for session, picks in _picks(db, rules, [model]).items():
            assert sum(1 for c in picks if c.security_id == stock) <= 1, (model, session)


def test_the_models_other_than_the_named_one_may_have_other_horizons_and_are_still_ignored(world):  # noqa: F811
    db = world["db"]
    rules15 = TradingRules.plan_15d()
    assert _picks(db, rules15, ["synthetic_h15"])  # the research rule reads its own horizon's model
    assert not _picks(db, rules15, [MAIN])  # a 5D model has no 15D records


def test_the_simulation_source_does_not_read_the_identity_tables_itself():
    import ast
    from pathlib import Path

    for name in ("source.py", "store.py", "ledger.py"):
        path = Path(source.__file__).with_name(name)
        modules = {
            n.module
            for n in ast.walk(ast.parse(path.read_text(encoding="utf8")))
            if isinstance(n, ast.ImportFrom) and n.module
        }
        assert not [m for m in modules if m.startswith("swing_trade_ml.db.models.identity")], name
