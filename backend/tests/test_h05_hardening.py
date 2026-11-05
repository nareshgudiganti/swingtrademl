# ruff: noqa: E501, N812, F811 (fixtures are imported by name; long test sentences)
"""h05 lane, readiness checks before protocol acceptance.

Training-basis scoring and parity, the single lane-stop rule, per-day data provenance, the higher-cost
sensitivity, separate reference prices and maturity, training-membership diagnostics, exclusion reporting and
the mechanical verdict."""

from __future__ import annotations

import random
from datetime import date

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select

from swing_trade_ml.brain.lanes import h05_features as F
from swing_trade_ml.brain.lanes import h05_models, h05_parity, h05_report, h05_service
from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_rules as R
from swing_trade_ml.brain.lanes import h05_verdict as V
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run, H05Signal
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml import market_context
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import build_features, on_balance_volume
from test_h05_service import (
    NOW,
    SESSIONS,
    SIGNAL,
    _token,
    _world,
    add_candle,
    add_stock,
    after,
    fake_models,
    future,
    lane,  # noqa: F401  (fixture)
    make_run,
    rows_of,
    weekdays,
)

# ----------------------------------------------------------------- feature basis


def test_the_training_obv_slope_is_the_old_obv_level_formula_not_todays():
    close = pd.Series(100 + np.cumsum(np.sin(np.arange(60)) * 2))
    volume = pd.Series(1_000 + (np.arange(60) % 7) * 150.0)
    obv = on_balance_volume(close, volume)
    expected = obv.diff(10) / obv.rolling(20).mean().abs().replace(0, np.nan)  # the 2026-08 formula
    today = obv.diff(10) / volume.rolling(20).mean().replace(0, np.nan)  # the formula since 2026-10-05
    got = F.old_obv_slope(close, volume)
    pd.testing.assert_series_equal(got, expected, check_names=False)
    assert not np.allclose(got.dropna(), today.dropna())


LONG = weekdays(date(2024, 9, 2), SIGNAL)  # 500+ sessions, more than the 400 bars production loads


def _series(db, symbol, token, start, seed, n=520):
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_active=True, segment="INDICES"
    )
    db.add(inst)
    db.flush()
    rng, price = np.random.default_rng(seed), start
    for d in LONG[-n:]:
        price *= 1 + rng.normal(0.0004, 0.01)
        add_candle(db, inst, d, (price * 0.999, price * 1.005, price * 0.995, price))


@pytest.fixture()
def market(db_session):
    market_context.clear_cache()
    _series(db_session, settings.BENCHMARK_INDEX_SYMBOL, 995001, 20_000.0, 11)
    _series(db_session, "INDIA VIX", 995002, 15.0, 12)
    yield
    market_context.clear_cache()


def _walk_stock(db, symbol, n=520):
    inst = Instrument(
        instrument_token=next(_token),
        tradingsymbol=symbol,
        exchange="NSE",
        is_active=True,
        instrument_type="EQ",
        is_watchlisted=True,
    )
    db.add(inst)
    db.flush()
    rng = np.random.default_rng(7)
    price = 100.0
    for d in LONG[-n:]:
        price *= 1 + rng.normal(0, 0.012)
        add_candle(db, inst, d, (price, price * 1.01, price * 0.99, price * (1 + rng.normal(0, 0.004))))
    return inst


def test_training_basis_changes_only_obv_slope_and_uses_the_full_history(db_session, market):
    inst = _walk_stock(db_session, "WALK1")
    basis = F.training_basis_frame(db_session, inst)
    raw = load_candles(db_session, inst.id, "day")
    plain = build_features(
        raw,
        F.load_index_candles(db_session, "day"),
        F.load_sector_candles(db_session, F.get_sector_index("WALK1"), "day"),
        F.load_vix_candles(db_session, "day"),
        F.load_market_breadth(db_session, "day"),
    )
    assert len(basis) == len(raw) == 520  # full history, not the newest 400 bars
    others = [c for c in plain.columns if c != "obv_slope"]
    pd.testing.assert_frame_equal(basis[others], plain[others])
    assert not np.allclose(basis["obv_slope"].dropna().tail(50), plain["obv_slope"].dropna().tail(50))


def _tiny_bundle(names, seed=1):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(300, len(names)))
    scaler = StandardScaler().fit(x)
    model = LogisticRegression().fit(scaler.transform(x), (x[:, 0] + rng.normal(size=300) > 0).astype(int))
    return {"estimator": model, "scaler": scaler, "feature_names": list(names)}


def test_training_basis_score_equals_a_hand_scored_row_and_never_imputes(db_session, market, monkeypatch):
    inst = _walk_stock(db_session, "WALK2")
    names = ["sma_10_ratio", "rsi_14", "obv_slope", "atr_14_pct", "volume_ratio_20"]
    bundle = _tiny_bundle(names)
    got = F.score_training_basis(db_session, inst, bundle)
    row = F.training_basis_frame(db_session, inst).iloc[[-1]][names]
    want = bundle["estimator"].predict_proba(bundle["scaler"].transform(row.to_numpy(float)))[0, 1]
    assert got.probability == pytest.approx(want) and got.price > 0
    # an input this model needs that is missing on the newest bar = no score; nothing is filled in
    real = F.build_features

    def with_a_hole(*a, **k):
        out = real(*a, **k)
        out.loc[out.index[-1], "rsi_14"] = np.nan
        return out

    monkeypatch.setattr(F, "build_features", with_a_hole)
    assert F.score_training_basis(db_session, inst, bundle) is None


def test_scoring_needs_the_220_bars_the_model_requires(db_session, market):
    inst = _walk_stock(db_session, "SHORTW", n=150)
    assert F.score_training_basis(db_session, inst, _tiny_bundle(["rsi_14"])) is None


def test_feature_code_is_pinned_and_a_changed_file_is_refused(db_session, tmp_path, monkeypatch):
    assert F.feature_code_sha256() == P.FEATURE_CODE_SHA256  # the pinned hashes match today's files
    _world(db_session, tmp_path, monkeypatch)
    models = h05_models.verify_models(db_session)
    ident = models["large"].identity()
    assert ident["feature_code"] == P.FEATURE_CODE_SHA256 and ident["primary_basis"] == P.PRIMARY_BASIS
    monkeypatch.setitem(P.FEATURE_CODE_SHA256, "ml/features.py", "0" * 64)
    with pytest.raises(P.ProtocolError, match="feature code changed"):
        h05_models.verify_models(db_session)


# ----------------------------------------------------------------- parity


def _window(names, rng, n=400, obv_scale=1.0):
    w = pd.DataFrame(rng.normal(size=(n, len(names))), columns=names)
    w["obv_training"] = w["obv_slope"] if "obv_slope" in names else 0.0
    return w


def test_parity_passes_on_the_training_basis_and_flags_a_drifted_formula():
    rng = np.random.default_rng(3)
    names = ["sma_10_ratio", "rsi_14", "obv_slope"]  # saved order follows the code's order
    w = _window(names, rng)
    scaler = StandardScaler().fit(w[names].to_numpy())
    # today's production formula gives obv_slope a different spread; the training formula does not
    today = w.copy()
    today["obv_slope"] = today["obv_slope"] * 3.0
    out = h05_parity.compare_window(today, names, scaler)
    assert out["order_matches_code"] is True
    assert out[P.PRIMARY_BASIS]["ok"] is True  # obv_training still reproduces the saved scaler
    assert out[P.DIAGNOSTIC_BASIS]["ok"] is False
    assert [b["input"] for b in out[P.DIAGNOSTIC_BASIS]["inputs_failing"]] == ["obv_slope"]


def test_parity_catches_a_shifted_mean_and_a_wrong_input_order():
    rng = np.random.default_rng(4)
    names = ["sma_10_ratio", "rsi_14"]
    w = _window(names, rng)
    scaler = StandardScaler().fit(w[names].to_numpy())
    shifted = w.assign(rsi_14=w["rsi_14"] + 1.0)  # one scaler-sd of drift in one input
    out = h05_parity.compare_window(shifted, names, scaler)
    assert out[P.PRIMARY_BASIS]["ok"] is False
    assert out[P.PRIMARY_BASIS]["inputs_failing"][0]["input"] == "rsi_14"
    assert (
        h05_parity.compare_window(
            w, list(reversed(names)), StandardScaler().fit(w[list(reversed(names))].to_numpy())
        )["order_matches_code"]
        is False
    )


def test_a_run_cannot_start_if_a_saved_model_fails_feature_parity(db_session, monkeypatch):
    from test_h05_service import starter  # noqa: F401

    monkeypatch.setattr(P, "require_runnable", lambda *a, **k: None)
    monkeypatch.setattr(h05_service, "verify_models", lambda db: fake_models())
    monkeypatch.setattr(h05_service, "build_universe", lambda db: ({"A1": "large"}, {}, "u"))
    monkeypatch.setattr(h05_service, "parity_report", lambda db, m: {"ok": False, "groups": {}})
    with pytest.raises(P.ProtocolError, match="feature parity failed"):
        h05_service.start_run(db_session, 1, date(2026, 10, 1), date(2026, 10, 30))
    assert db_session.scalar(select(H05Run)) is None


def test_the_run_stores_its_parity_evidence(db_session, monkeypatch):
    monkeypatch.setattr(P, "require_runnable", lambda *a, **k: None)
    monkeypatch.setattr(h05_service, "verify_models", lambda db: fake_models())
    monkeypatch.setattr(h05_service, "build_universe", lambda db: ({"A1": "large"}, {}, "u"))
    monkeypatch.setattr(
        h05_service, "parity_report", lambda db, m: {"ok": True, "groups": {"large": {"n": 1}}}
    )
    run = h05_service.start_run(db_session, 1, date(2026, 10, 1), date(2026, 10, 30))
    assert run.parity["ok"] is True and run.parity["groups"]["large"] == {"n": 1}


# ----------------------------------------------------------------- one consistent failure rule


def test_a_failed_check_for_any_one_group_stops_the_whole_lane_and_persists_why(
    db_session, lane, monkeypatch
):
    for s in ("L1", "M1", "S1"):
        add_stock(db_session, s)
        lane.scores[s] = 0.6
    run = make_run(db_session, {"L1": "large", "M1": "mid", "S1": "small"})

    def mid_model_missing(db):
        raise P.ProtocolError("mid model id 16: model file swing_classifier_midcap_v2.joblib not found")

    monkeypatch.setattr(h05_service, "verify_models", mid_model_missing)
    stopped = h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    assert stopped["stopped"] and "mid model id 16" in stopped["reason"]
    # nothing at all was recorded, for ANY group, and no model (no replacement) was called
    assert not rows_of(db_session, run) and not db_session.execute(select(H05GroupDay)).scalars().all()
    assert lane.calls == []
    event = db_session.execute(select(H05Event)).scalar_one()
    assert (event.signal_day, event.kind) == (
        SIGNAL,
        "lane_stopped_model_check",
    ) and "mid model" in event.detail
    # the day shows up as not recorded in the report, and the lane resumes once the identities match again
    rep = h05_report.build_report(db_session)
    assert (
        str(SIGNAL) in rep["runs"][0]["days_missed"]
        and rep["runs"][0]["events"][0]["kind"] == "lane_stopped_model_check"
    )
    monkeypatch.setattr(h05_service, "verify_models", lambda db: fake_models())
    h05_service.score_day(db_session, run, after(SIGNAL, 1) if False else SIGNAL, now=NOW)
    assert len(rows_of(db_session, run)) == 3
    assert str(SIGNAL) not in h05_report.build_report(db_session)["runs"][0]["days_missed"]


def test_a_changed_model_identity_also_stops_the_whole_lane(db_session, lane, monkeypatch):
    add_stock(db_session, "L1")
    lane.scores["L1"] = 0.6
    run = make_run(db_session, {"L1": "large"})
    monkeypatch.setattr(h05_service, "verify_models", lambda db: fake_models(sha="d" * 64))
    out = h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    assert out["stopped"] and db_session.execute(select(H05Event)).scalar_one().detail == out["reason"]


# ----------------------------------------------------------------- the primary score selects; the diagnostic never does


def test_the_primary_score_selects_and_the_production_path_score_is_only_a_diagnostic(db_session, lane):
    groups = {f"L{i}": "large" for i in range(8)}
    for i, s in enumerate(groups):
        add_stock(db_session, s)
        lane.scores[s] = 0.5 + i / 100  # primary: L7 best
        lane.alt[s] = 0.9 - i / 100  # production path: the opposite order
    run = make_run(db_session, groups)
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    rows = rows_of(db_session, run)
    assert {s for s, r in rows.items() if r.selected} == {"L7", "L6", "L5", "L4", "L3"}
    assert rows["L0"].score_production_path == pytest.approx(0.9) and rows["L7"].score == pytest.approx(0.57)
    gap = h05_report.summarise_group([h05_report._row(r) for r in rows.values()])["diagnostics"][
        "production_path_score_gap"
    ]
    assert gap["mean_rank_correlation"] == pytest.approx(-1.0) and gap["mean_top5_overlap"] == 2


# ----------------------------------------------------------------- provenance of daily market data


def test_each_day_records_where_its_data_came_from_without_hashing_the_whole_dataset(db_session, lane):
    add_stock(db_session, "PA")
    add_stock(db_session, "PB")
    add_stock(db_session, "OTHER")  # not in the universe
    lane.scores.update({"PA": 0.6, "PB": 0.7})
    run = make_run(db_session, {"PA": "large", "PB": "mid"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    gd = {g.group: g for g in db_session.execute(select(H05GroupDay)).scalars()}
    prov = gd["large"].provenance
    assert (
        prov["signal_day"] == str(SIGNAL)
        and prov["with_signal_bar"] == 1
        and prov["nifty_sessions"] == len(SESSIONS)
    )
    assert (
        prov["nifty_last_session"] == str(SESSIONS[-1])
        and "bars_sha256" in prov
        and gd["mid"].provenance["with_signal_bar"] == 1
    )
    # the fingerprint covers the group's signal-day bars only: changing an unrelated stock or an old bar leaves it
    row = {"symbol": "PA", "bar": (100.0, 100.0, 100.0, 100.0, 100_000.0)}
    h1 = h05_service._provenance(db_session, SIGNAL, SESSIONS, [row])["bars_sha256"]
    assert h1 == h05_service._provenance(db_session, SIGNAL, SESSIONS, [row])["bars_sha256"]
    assert (
        h1
        != h05_service._provenance(
            db_session, SIGNAL, SESSIONS, [{**row, "bar": (100.0, 101.0, 100.0, 100.0, 1.0)}]
        )["bars_sha256"]
    )


def test_outcomes_record_which_bars_they_were_scored_from(db_session, lane):
    inst = add_stock(db_session, "OUT1")
    lane.scores["OUT1"] = 0.6
    run = make_run(db_session, {"OUT1": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    future(db_session, inst)
    h05_service.evaluate(db_session, run)
    prov = rows_of(db_session, run)["OUT1"].outcome_provenance
    assert (
        prov["window_sessions"] == [str(after(SIGNAL, k)) for k in range(1, 6)]
        and len(prov["window_bars_sha256"]) == 64
    )


# ----------------------------------------------------------------- the higher-cost sensitivity


def test_the_stress_trade_costs_more_than_the_headline_trade_on_the_same_bars():
    sess = weekdays(date(2026, 10, 5), date(2026, 10, 30))
    sig = sess[1]
    bars = dict.fromkeys(sess, (100.0, 100.5, 99.5, 100.0))
    base = R.simulate_trade(bars, sess, sig, 100.0, "mid")
    hard = R.simulate_trade(bars, sess, sig, 100.0, "mid", stress=True)
    assert base.status == hard.status == "expiry"
    assert hard.entry_fill > base.entry_fill and hard.net_return < base.net_return - 0.005
    assert hard.costs_inr == pytest.approx(
        R.charges(hard.entry_fill * int(P.NOTIONAL_INR // hard.entry_fill), "BUY", 2.0)
        + R.charges(hard.exit_fill * int(P.NOTIONAL_INR // hard.entry_fill), "SELL", 2.0)
    )


def test_evaluate_stores_the_stress_result_next_to_the_headline(db_session, lane):
    inst = add_stock(db_session, "STR1")
    lane.scores["STR1"] = 0.6
    run = make_run(db_session, {"STR1": "small"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    future(db_session, inst)
    h05_service.evaluate(db_session, run)
    r = rows_of(db_session, run)["STR1"]
    assert r.trade_status == r.trade_status_stress == "expiry" and r.net_return_stress < r.net_return
    group = h05_report.summarise_group([h05_report._row(r)])
    assert group["shadow_trade"]["higher_cost_sensitivity"]["assumption"].startswith(
        "every fill 30 bps worse"
    )


# ----------------------------------------------------------------- two reference prices, two maturities


def test_label_uses_the_signal_close_and_the_trade_uses_the_entry_fill(db_session, lane):
    """Opens +3% above the signal close and stays there: the model's question is YES (+3% vs the signal close),
    while the trade, entered at that higher price, goes nowhere and loses its costs."""
    inst = add_stock(db_session, "GAP1")
    lane.scores["GAP1"] = 0.6
    run = make_run(db_session, {"GAP1": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    gapped = {f"n{k}": (103.0, 103.0, 103.0, 103.0) for k in range(1, 6)}
    future(db_session, inst, **gapped)
    h05_service.evaluate(db_session, run)
    r = rows_of(db_session, run)["GAP1"]
    assert r.signal_close == 100.0 and r.label_close5 == 103.0 and r.label_hit == 1  # reference: signal close
    assert r.entry_open == 103.0 and r.entry_fill == pytest.approx(
        103.0 * (1 + P.SLIPPAGE_BPS["large"] / 10_000)
    )
    assert r.trade_status == "expiry" and r.net_return < 0  # reference: entry fill


SMALL = weekdays(date(2026, 10, 5), date(2026, 11, 20))


def _flat(extra=None):
    b = dict.fromkeys(SMALL, (100.0, 100.0, 100.0, 100.0))
    b.update(extra or {})
    return b


def test_both_outcomes_mature_on_session_five_not_session_four_or_six():
    sig = SMALL[3]
    five = R.sessions_after(SMALL, sig, 5)
    # 4 sessions known: both pending
    four_known = SMALL[: SMALL.index(five[3]) + 1]
    assert R.simulate_trade(_flat(), four_known, sig, 100.0, "large").status == "pending"
    assert R.endpoint_outcome(dict.fromkeys(four_known, 100.0), four_known, sig).status == "pending"
    # 5 sessions known: both final, and the label's day equals the expiring trade's exit day
    five_known = SMALL[: SMALL.index(five[4]) + 1]
    trade = R.simulate_trade(_flat(), five_known, sig, 100.0, "large")
    label = R.endpoint_outcome(dict.fromkeys(five_known, 100.0), five_known, sig)
    assert (
        trade.status == "expiry" and label.status == "evaluated" and trade.exit_day == label.day5 == five[4]
    )
    # session 6 is never read: a crazy candle there changes nothing
    poisoned = _flat({SMALL[SMALL.index(five[4]) + 1]: (1.0, 999.0, 1.0, 999.0)})
    again = R.simulate_trade(poisoned, SMALL, sig, 100.0, "large")
    assert (again.status, again.exit_day, again.net_return) == (
        trade.status,
        trade.exit_day,
        trade.net_return,
    )
    closes = {d: b[3] for d, b in poisoned.items()}
    assert R.endpoint_outcome(closes, SMALL, sig).label == label.label


def test_an_early_exit_is_final_while_the_label_is_still_pending():
    sig = SMALL[3]
    three_known = SMALL[: SMALL.index(R.sessions_after(SMALL, sig, 5)[2]) + 1]
    bars = _flat({R.sessions_after(SMALL, sig, 5)[1]: (100.0, 103.0, 100.0, 102.5)})  # target on session 2
    assert R.simulate_trade(bars, three_known, sig, 100.0, "large").status == "target"
    assert R.endpoint_outcome({d: b[3] for d, b in bars.items()}, three_known, sig).status == "pending"


# ----------------------------------------------------------------- reporting: exclusions, NOT SCORED, membership


def test_every_exclusion_and_not_scored_event_reaches_the_report(db_session, lane):
    add_stock(db_session, "OK1")
    add_stock(db_session, "STALE1", last=after(SIGNAL, -1))
    add_stock(db_session, "SHORT1", n=100)
    lane.scores.update({"OK1": 0.8, "STALE1": 0.7, "SHORT1": 0.7})
    run = make_run(
        db_session,
        {"OK1": "large", "STALE1": "small", "SHORT1": "large"},
        excluded={"BOTH1": "ambiguous_group: in mid and small"},
    )
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    rep = h05_report.build_report(db_session)
    r = rep["runs"][0]
    assert r["universe_excluded"] == {"BOTH1": "ambiguous_group: in mid and small"}
    large = r["groups"]["large"]["not_scored_events"]
    assert {"symbol": "SHORT1", "reason": "short_history", "days": 1} in large
    assert {"symbol": "STALE1", "reason": "stale_data", "days": 1} in r["groups"]["small"][
        "not_scored_events"
    ]
    md = h05_report.render_markdown(rep)
    assert "BOTH1" in md and "SHORT1: short_history" in md and "STALE1: stale_data" in md


def test_training_membership_is_a_breakdown_of_the_same_frozen_result():
    def row(day, sym, trained, sel, net, hit):
        return {
            "signal_day": day,
            "symbol": sym,
            "group": "mid",
            "status": "scored",
            "not_scored_reason": None,
            "score": 0.6,
            "score_production_path": 0.6,
            "selected": sel,
            "repeat_blocked": False,
            "trained_on_symbol": trained,
            "label_status": "evaluated",
            "label_hit": hit,
            "trade_status": "expiry",
            "net_return": net,
            "trade_status_stress": "expiry",
            "net_return_stress": net - 0.01,
            "ambiguous": False,
            "gap_fill": False,
            "trade_flags": [],
        }

    rows = []
    for d in weekdays(date(2026, 10, 5), date(2026, 10, 9)):
        rows += [
            row(d, "IN1", True, True, 0.02, 1),
            row(d, "IN2", True, False, -0.01, 0),
            row(d, "OUT1", False, True, -0.02, 0),
            row(d, "OUT2", False, False, 0.0, 0),
        ]
    s = h05_report.summarise_group(rows)
    mem = s["diagnostics"]["training_membership"]
    assert mem["in_training"]["distinct_stocks"] == 2 and mem["not_in_training"]["distinct_stocks"] == 2
    assert mem["in_training"]["shadow_trade"]["picks"]["mean_net_return"] == pytest.approx(0.02)
    assert mem["not_in_training"]["shadow_trade"]["picks"]["mean_net_return"] == pytest.approx(-0.02)
    # the headline is the whole group, unchanged by the breakdown, and the breakdown says it is not a second chance
    assert (
        mem["in_training"]["counted_picks"] + mem["not_in_training"]["counted_picks"]
        == s["counted_selections"]
    )
    assert s["shadow_trade"]["counted_picks"]["mean_net_return"] == pytest.approx(0.0)
    assert "not a second chance to pass" in s["diagnostics"]["note"]
    assert "verdict" not in s["diagnostics"]["training_membership"]["in_training"]


# ----------------------------------------------------------------- the mechanical verdict


def _edge(mean, n=60, seed=1, sd=0.004):
    rng = random.Random(seed)
    return [mean + rng.gauss(0, sd) for _ in range(n)]


def _verdicts(run):
    return run["selection"]["verdict"], run["economic"]["verdict"]


def test_run_decision_gives_two_separate_verdicts_by_the_frozen_rule():
    # (trade edge over the average stock, label edge, picks' own daily net return, short-top-5 share)
    good = V.run_decision(_edge(0.015), _edge(0.3, sd=0.05), _edge(0.012), 0.0)
    assert _verdicts(good) == (V.PASS, V.PASS)
    assert _verdicts(V.run_decision(_edge(-0.015), _edge(0.3, sd=0.05), _edge(-0.012), 0.0)) == (V.FAIL, V.FAIL)
    assert _verdicts(V.run_decision(_edge(0.0, sd=0.02), _edge(0.0, sd=0.2), _edge(0.0, sd=0.02), 0.0)) == (
        V.INCONCLUSIVE,
        V.INCONCLUSIVE,
    )
    # a ranking that is clearly backwards blocks a selection PASS even when the trade edge is positive
    vetoed = V.run_decision(_edge(0.015), _edge(-0.3, sd=0.05), _edge(0.012), 0.0)
    assert vetoed["selection"]["verdict"] == V.INCONCLUSIVE and vetoed["selection"]["label_veto"] is True
    # too few matured days, or a top 5 that was often short, cannot give either verdict
    few = V.run_decision(_edge(0.05, n=20), _edge(0.3, n=20), _edge(0.05, n=20), 0.0)
    assert "only 20 matured" in few["why"] and _verdicts(few) == (V.INCONCLUSIVE, V.INCONCLUSIVE)
    assert _verdicts(V.run_decision(_edge(0.05), _edge(0.3), _edge(0.05), 0.5)) == (V.INCONCLUSIVE, V.INCONCLUSIVE)


def test_beating_a_negative_baseline_is_a_selection_pass_and_never_an_economic_pass():
    """The picks lose 0.2% a day, the average stock loses 0.5%: the ranking works, the money does not."""
    run = V.run_decision(_edge(0.003, sd=0.001), _edge(0.3, sd=0.05), _edge(-0.002, sd=0.001), 0.0)
    assert _verdicts(run) == (V.PASS, V.FAIL)
    # also when the picks are only a hair above zero in their average but the range reaches below it
    run = V.run_decision(_edge(0.003, sd=0.001), _edge(0.3, sd=0.05), _edge(0.0003, sd=0.01), 0.0)
    assert run["selection"]["verdict"] == V.PASS and run["economic"]["verdict"] == V.INCONCLUSIVE
    assert "relative skill, no economic result" in V.reading(V.PASS, V.FAIL)


def test_money_from_the_market_without_selection_skill_is_not_called_a_model_result():
    run = V.run_decision(_edge(0.0, sd=0.02), _edge(0.0, sd=0.2), _edge(0.01, sd=0.002), 0.0)
    assert _verdicts(run) == (V.INCONCLUSIVE, V.PASS)
    assert "model advantage over the baseline was not established" in V.reading(V.INCONCLUSIVE, V.PASS)
    assert V.reading(V.FAIL, V.PASS).startswith("Profitable under the stated assumptions; model advantage over the baseline was not established")
    assert {(s, e) for s in (V.PASS, V.FAIL, V.INCONCLUSIVE) for e in (V.PASS, V.FAIL, V.INCONCLUSIVE)} == set(
        V.READING
    )


def _runs(sel, eco):
    return [{"selection": {"verdict": a}, "economic": {"verdict": b}} for a, b in zip(sel, eco, strict=True)]


def test_three_runs_combine_each_verdict_type_separately_and_inconclusive_is_allowed():
    p, f, i = V.PASS, V.FAIL, V.INCONCLUSIVE
    good, bad = _edge(0.012, n=180), _edge(-0.012, n=180)
    both = V.combined_decision(_runs([p, p, i], [p, p, i]), good, good)
    assert (both["selection"]["verdict"], both["economic"]["verdict"]) == (V.PASS, V.PASS)
    # selection passes in 3 runs while the picks lose money: ECONOMIC fails, SELECTION still passes
    split = V.combined_decision(_runs([p, p, p], [f, f, f]), good, bad)
    assert (split["selection"]["verdict"], split["economic"]["verdict"]) == (V.PASS, V.FAIL)
    assert "relative skill, no economic result" in split["reading"]
    # the pooled picks must be above zero for an economic PASS even when 3 runs pass
    assert V.combined_decision(_runs([p, p, p], [p, p, p]), good, _edge(0.0, sd=0.02, n=180))["economic"][
        "verdict"
    ] == V.INCONCLUSIVE
    assert V.combined_decision(_runs([p, i, i], [p, i, i]), good, good)["selection"]["verdict"] == V.INCONCLUSIVE
    assert V.combined_decision(_runs([p, p, f], [p, p, f]), good, good)["economic"]["verdict"] == V.INCONCLUSIVE
    assert V.combined_decision(_runs([f, f, p], [f, f, p]), good, good)["selection"]["verdict"] == V.FAIL
    assert V.combined_decision(_runs([p, p, p], [p, p, p]), bad, bad)["economic"]["verdict"] == V.FAIL
    waiting = V.combined_decision(_runs([p, p], [p, p]), good, good)  # a run is not final yet
    assert waiting["selection"]["verdict"] == V.INCONCLUSIVE and "of 3 runs are final" in waiting["selection"]["why"]


def _seed_run(db, run_no, days, edge, label_edge=0.3):
    """A closed, fully matured run: 12 stocks a day in the large group, the top 5 by score are the picks."""
    run = H05Run(
        run_no=run_no,
        protocol_code=P.PROTOCOL_CODE,
        protocol_hash=P.protocol_hash(),
        status="closed",
        start_day=days[0],
        end_day=days[-1],
        models={},
        universe={"groups": {}, "excluded": {}},
        universe_hash="u",
    )
    db.add(run)
    db.flush()
    rng = random.Random(run_no)
    for d in days:
        db.add(
            H05GroupDay(
                run_id=run.id,
                signal_day=d,
                group="large",
                universe_n=12,
                scored_n=12,
                not_scored_n=0,
                selected_n=5,
                shortfall=0,
            )
        )
        for k in range(12):
            pick = k < 5
            net = -0.005 + rng.gauss(0, 0.004) + (edge if pick else 0.0)
            hit = int(rng.random() < (0.25 + (label_edge if pick else 0.0)))
            db.add(
                H05Signal(
                    run_id=run.id,
                    signal_day=d,
                    symbol=f"S{k}",
                    group="large",
                    status="scored",
                    score=1 - k / 20,
                    group_rank=k + 1,
                    selected=pick,
                    repeat_blocked=False,
                    trained_on_symbol=k % 2 == 0,
                    label_status="evaluated",
                    label_hit=hit,
                    trade_status="expiry",
                    net_return=net,
                    trade_status_stress="expiry",
                    net_return_stress=net - 0.01,
                    ambiguous=False,
                    gap_fill=False,
                    trade_flags=[],
                )
            )
    db.flush()
    return run


DAYS = weekdays(date(2026, 1, 5), date(2026, 12, 31))


def _three(db, edge):
    for n in (1, 2, 3):
        _seed_run(db, n, DAYS[(n - 1) * 50 : n * 50], edge)


def test_before_acceptance_the_report_measures_but_calculates_no_verdict(db_session, monkeypatch):
    monkeypatch.setattr(h05_service, "market_sessions", lambda db: list(SESSIONS))
    _three(db_session, 0.02)
    rep = h05_report.build_report(db_session)
    assert rep["protocol_accepted"] is False and rep["verdict"]["state"] == "not_calculated"
    assert rep["runs"][0]["groups"]["large"]["shadow_trade"]["counted_picks"]["mean_net_return"] is not None
    assert "not been accepted" in h05_report.render_markdown(rep)


def test_after_acceptance_the_verdict_is_calculated_mechanically_when_outcomes_mature(
    db_session, monkeypatch
):
    monkeypatch.setattr(h05_service, "market_sessions", lambda db: list(SESSIONS))
    monkeypatch.setattr(P, "accepted", lambda settings=None: True)
    _three(db_session, 0.02)
    rep = h05_report.build_report(db_session)
    large = rep["verdict"]["large"]
    assert [_verdicts(large["runs"][n]) for n in (1, 2, 3)] == [(V.PASS, V.PASS)] * 3
    assert large["combined"]["selection"]["verdict"] == V.PASS and large["combined"]["economic"]["verdict"] == V.PASS
    text = h05_report.render_markdown(rep)
    assert "Verdict (frozen rule" in text and "SELECTION PASS" in text and "ECONOMIC PASS" in text
    assert "NOT an exact replay" in text


def test_a_backwards_edge_fails_and_an_open_run_waits(db_session, monkeypatch):
    monkeypatch.setattr(h05_service, "market_sessions", lambda db: list(SESSIONS))
    monkeypatch.setattr(P, "accepted", lambda settings=None: True)
    _three(db_session, -0.02)
    rep = h05_report.build_report(db_session)
    combined = rep["verdict"]["large"]["combined"]
    assert (combined["selection"]["verdict"], combined["economic"]["verdict"]) == (V.FAIL, V.FAIL)
    run3 = db_session.scalar(select(H05Run).where(H05Run.run_no == 3))
    run3.status = "active"
    db_session.flush()
    waiting = h05_report.build_report(db_session)["verdict"]["large"]
    assert waiting["runs"][3]["final"] is False and "waiting" in waiting["runs"][3]["why"]
    assert waiting["combined"]["selection"]["verdict"] == V.INCONCLUSIVE
    assert "of 3 runs are final" in waiting["combined"]["economic"]["why"]


def test_a_run_with_unmatured_outcomes_waits_instead_of_deciding(db_session, monkeypatch):
    monkeypatch.setattr(h05_service, "market_sessions", lambda db: list(SESSIONS))
    monkeypatch.setattr(P, "accepted", lambda settings=None: True)
    run = _seed_run(db_session, 1, DAYS[:50], 0.02)
    last = db_session.execute(select(H05Signal).where(H05Signal.run_id == run.id)).scalars().first()
    last.label_status = "pending"
    db_session.flush()
    info = h05_report.build_report(db_session)["verdict"]["large"]["runs"][1]
    assert info["final"] is False and "not matured" in info["why"]


def test_a_day_with_too_few_eligible_stocks_is_not_evidence():
    """U2: fewer than 10 eligible stocks on a day and that day leaves the verdict series."""

    def row(day, sym, sel, net):
        return {
            "signal_day": day,
            "symbol": sym,
            "group": "mid",
            "status": "scored",
            "not_scored_reason": None,
            "score": 0.6,
            "score_production_path": 0.6,
            "selected": sel,
            "repeat_blocked": False,
            "trained_on_symbol": True,
            "label_status": "evaluated",
            "label_hit": 1 if sel else 0,
            "trade_status": "expiry",
            "net_return": net,
            "trade_status_stress": "expiry",
            "net_return_stress": net,
            "ambiguous": False,
            "gap_fill": False,
            "trade_flags": [],
        }

    days = weekdays(date(2026, 10, 5), date(2026, 10, 9))
    rows = []
    for k, d in enumerate(days):
        n = 12 if k < 3 else 6  # the last two days have only 6 eligible stocks
        rows += [row(d, f"S{i}", i < 5, 0.02 if i < 5 else -0.01) for i in range(n)]
    series = h05_report.group_series(rows)
    assert len(series["trade_edge"]) == 3 and len(series["picks_daily_net"]) == 3 and len(series["label_edge"]) == 3
