# backend/tests/test_brain_module_ablation.py
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from swing_trade_ml.brain import module_ablation as ma
from swing_trade_ml.brain.module import REGISTRY, Mode
from swing_trade_ml.brain.replay_scoring import StrictOutcome

D = date(2026, 7, 13)


def _d(symbol, word, downgraded_from=None, kind="idea", overruled=None):
    return SimpleNamespace(
        symbol=symbol, word=word, downgraded_from=downgraded_from, kind=kind, overruled_word=overruled
    )


def _o(status, net):
    return StrictOutcome(status, net, 5, False, False, D)


def test_registry_without_leaves_out_exactly_one_module():
    import swing_trade_ml.brain.modules  # noqa: F401  (registers every module)

    ids = [c.manifest.id for c in REGISTRY.all()]
    reg = ma.registry_without("M10")
    assert [c.manifest.id for c in reg.all()] == [i for i in ids if i != "M10"]
    assert [c.manifest.id for c in ma.registry_without(None).all()] == ids


def test_plan_tests_on_modules_and_explains_every_skip():
    import swing_trade_ml.brain.modules  # noqa: F401

    modes = {"M10": Mode.SHADOW}
    test, skip = ma.plan(REGISTRY, modes)
    assert "M10" not in test and "shadow" in skip["M10"]
    assert "M07" in test  # mandatory: always on, tested as the fallback check
    assert set(ma.NOT_JUDGEABLE) <= set(skip)
    assert set(test) | set(skip) == {c.manifest.id for c in REGISTRY.all()}


def test_liked_means_trade_or_a_lowered_trade_and_holdings_are_left_out():
    js = ma.judged_from(
        [
            _d("A", "TRADE"),
            _d("B", "WATCH", downgraded_from="TRADE"),
            _d("C", "WAIT"),
            _d("H", "HOLD", kind="holding"),
            _d("E", "TRADE", overruled="AVOID"),
        ],
        D,
    )
    assert [(j.symbol, j.liked) for j in js] == [("A", True), ("B", True), ("C", False), ("E", False)]


def test_compare_counts_changes_and_scores_only_liked_ideas():
    base = ma.judged_from([_d("A", "TRADE"), _d("B", "WAIT"), _d("C", "TRADE")], D)
    variant = ma.judged_from([_d("A", "TRADE"), _d("B", "TRADE"), _d("C", "WAIT")], D)
    outcomes = {("A", D): _o("target", 0.06), ("B", D): _o("stop", -0.045), ("C", D): _o("target", 0.07)}
    r = ma.compare(base, variant, outcomes)
    assert (r["changed_words"], r["liked_added"], r["liked_dropped"], r["liked"]) == (2, 1, 1, 2)
    assert abs(r["avg_net"] - 0.0075) < 1e-12 and r["hit_rate"] == 0.5


def test_readings_name_useless_modules_and_an_unsafe_risk_gate():
    base = {"avg_net": 0.01}
    assert "adds nothing" in ma.reading("M11", {"changed_words": 0, "avg_net": 0.01}, base)
    assert "helps" in ma.reading("M10", {"changed_words": 3, "avg_net": -0.01}, base)
    assert "hurts" in ma.reading("M10", {"changed_words": 3, "avg_net": 0.02}, base)
    assert ma.reading("M07", {"trade_words": 0}, base).startswith("safe")
    assert ma.reading("M07", {"trade_words": 2}, base).startswith("UNSAFE")


def test_a_stopped_run_resumes_from_the_checkpoint(tmp_path, monkeypatch):
    import swing_trade_ml.brain.modules  # noqa: F401
    from swing_trade_ml.brain import replay_score, service

    calls = []

    def fake_replay(db, *, start, end, asof_model, registry):
        calls.append(len(registry.all()))
        return [SimpleNamespace(run_id=f"r{len(calls)}")]

    monkeypatch.setattr(service, "load_modes", lambda db: {})
    monkeypatch.setattr(service, "decisions_for", lambda db, run_id: [_d("A", "TRADE")])
    monkeypatch.setattr(replay_score, "load_bars", lambda db, symbols, upto: {})
    cp = tmp_path / "checkpoint.json"
    kw = {
        "days": [D],
        "asof_model": None,
        "checkpoint": cp,
        "upto": D,
        "only": ["M07"],
        "replay": fake_replay,
    }
    first = ma.run(None, **kw)
    assert len(calls) == 2  # base + M07
    again = ma.run(None, **kw)
    assert len(calls) == 2  # nothing replayed again
    assert first == again
    assert first["without"]["M07"]["reading"].startswith("UNSAFE")  # the fake says TRADE regardless
    assert "## Not tested" in ma.plain_report(first)


# --- one real replayed day (test database) ------------------------------------------------------


def test_the_real_brain_without_the_risk_gate_never_says_trade(db_session):
    from swing_trade_ml.brain.replay_week import run_replay_week
    from test_brain_golden_day import GOLDEN_DAY, STOCKS, _build_market

    _build_market(db_session)
    symbols = [s[0] for s in STOCKS]

    def replay(db, *, start, end, asof_model, registry):
        return run_replay_week(
            db, start=start, end=end, symbols=symbols, asof_model=asof_model, registry=registry
        )

    for without in ("M07", "M10", None):
        judged = ma.run_variant(db_session, [GOLDEN_DAY], without, asof_model=None, replay=replay)
        assert {j.symbol for j in judged} == set(symbols)
        if without == "M07":
            assert all(j.word != "TRADE" for j in judged)
