# ruff: noqa: E501 (long plain-English test text)
"""#247: corporate actions and training-to-scoring input consistency (verification tests; nothing here changes the app).

Findings note: docs/verification/247-corporate-actions-inputs.md. Existing coverage that this file does not repeat, and
that the note cites and re-runs: test_corporate_action_accounting.py (split and bonus on open paper positions),
test_split_check.py, test_price_change_detector.py, test_candle_corrections.py, test_train_serve_parity.py (inputs
identical in training and scoring), test_brain_m01_quality.py, test_stock_split.py is NOT about corporate actions
(it splits the research stock list).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select

from swing_trade_ml.brain.lanes import h05_parity
from swing_trade_ml.brain.lanes import h05_protocol as proto
from swing_trade_ml.brain.modules.m01_quality.quality import assess_bars
from swing_trade_ml.core.market_session import IST, last_closed_trading_day
from swing_trade_ml.db.models.corporate_actions import CorporateAction
from swing_trade_ml.db.models.identity import Security
from swing_trade_ml.ml import predict, registry
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features
from swing_trade_ml.services.identity import resolve, writer
from test_brain_m01_quality import MON
from test_brain_m01_quality import _bars as quality_bars
from test_features import _synthetic_ohlcv
from test_portfolio_risk_layer import _instrument, _strategy

# ------------------------------------------------------------------------------- (a) what a split does to stored prices


def _contexts(n: int = 400):
    return _synthetic_ohlcv(7, n), _synthetic_ohlcv(13, n), _synthetic_ohlcv(21, n), pd.DataFrame(
        {"ts": _synthetic_ohlcv(1, n)["ts"], "breadth_pct_above_sma50": 0.5, "breadth_advance_pct": 0.5}
    )


def _with_split(df: pd.DataFrame, at: int, factor: float = 0.5, adjust_history: bool = False) -> pd.DataFrame:
    """The same economic series as stored by a data vendor. RAW (default): prices are as traded, so from bar `at` they
    are `factor` times the earlier level (a 2-for-1 split is 0.5) and volume is scaled the other way: a visible step.
    ADJUSTED: history is restated so there is no step (here: the whole series at the post-split level)."""
    out = df.copy()
    cols = ["open", "high", "low", "close"]
    if adjust_history:
        out[cols] = out[cols] * factor
        out["volume"] = out["volume"] / factor
    else:
        out.loc[at:, cols] = out.loc[at:, cols] * factor
        out.loc[at:, "volume"] = out.loc[at:, "volume"] / factor
    return out


def test_an_unadjusted_split_reaches_the_model_inputs_as_a_fifty_percent_crash_and_an_adjusted_one_does_not():
    base = _synthetic_ohlcv(42, 400)
    index_df, sector_df, vix_df, breadth_df = _contexts()
    raw = build_features(_with_split(base, 380), index_df, sector_df, vix_df, breadth_df)
    adjusted = build_features(_with_split(base, 380, adjust_history=True), index_df, sector_df, vix_df, breadth_df)
    assert raw["return_1d"].iloc[380] == pytest.approx(-0.5, abs=0.02)  # the model is told the stock halved overnight
    assert abs(adjusted["return_1d"].iloc[380]) < 0.1  # on adjusted prices it is an ordinary day
    assert raw["return_5d"].iloc[384] < -0.4 and adjusted["return_5d"].iloc[384] > -0.2
    # The long-window inputs stay wrong long after the day itself (the 200-day average still holds pre-split prices)
    assert raw["sma_200_ratio"].iloc[399] < adjusted["sma_200_ratio"].iloc[399] - 0.2


def test_a_split_leaves_no_trace_in_the_v1_scoring_path_it_reads_stored_candles_only():
    """Code-reading pin: `strategies/ml_swing.py` and `ml/predict.py` read candles and market context only; neither reads
    corporate actions. If that changes, this test names it."""
    from pathlib import Path

    import swing_trade_ml.strategies.ml_swing as ml_swing

    for module in (ml_swing, predict):
        text = Path(module.__file__).read_text(encoding="utf8")
        assert "corporate_action" not in text and "CorporateAction" not in text and "split_check" not in text


def _real_ml_swing_decision(db, monkeypatch, df: pd.DataFrame, name: str):
    """The REAL MLSwingStrategy.evaluate on `df` (>= 260 bars), with the trained model and the market-context loaders
    replaced by fixed stand-ins (the model says 95%). Returns its decision."""
    from swing_trade_ml.strategies import ml_swing

    class Estimator:
        def predict_proba(self, x):
            return np.array([[0.05, 0.95]])

    class Scaler:
        def transform(self, x):
            return x

    bundle = {"feature_names": ["f"], "scaler": Scaler(), "estimator": Estimator()}
    model = SimpleNamespace(
        name="swing_classifier", version="v-test", prediction_horizon_days=15, label_kind="barrier",
        target_return_pct=0.08, stop_return_pct=0.04,
    )
    empty = pd.DataFrame(columns=["ts", "close"])
    monkeypatch.setattr(ml_swing, "get_active_model", lambda db_, n: model)
    monkeypatch.setattr(ml_swing, "_get_bundle", lambda m: bundle)
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles", "load_market_breadth"):
        monkeypatch.setattr(ml_swing, loader, lambda *a, **k: empty)
    monkeypatch.setattr(
        ml_swing, "build_features",
        lambda d, *a, **k: pd.DataFrame({"f": [1.0] * len(d), "nifty_trend_regime": [1.0] * len(d)}),
    )
    strat, inst = _strategy(db, name=f"s247_{name}"), _instrument(db, f"S247{name.upper()[:12]}")
    return ml_swing.MLSwingStrategy(strat).evaluate(df, inst, db)


def _quiet_series(n: int = 300, split_at: int | None = None, factor: float = 0.5) -> pd.DataFrame:
    end = last_closed_trading_day(datetime.now(UTC))
    days = [end - timedelta(days=n - 1 - i) for i in range(n)]
    close = np.array([100.0 + 0.01 * i + (0.2 if i % 2 else 0.0) for i in range(n)])
    scale = np.ones(n)
    if split_at is not None:
        scale[split_at:] = factor
    return pd.DataFrame(
        {
            "ts": [datetime(d.year, d.month, d.day, tzinfo=IST) for d in days],
            "open": close * scale, "high": (close + 1.0) * scale, "low": (close - 1.0) * scale, "close": close * scale,
            "volume": [250_000.0] * n,
        }
    )


def test_the_clean_series_control_is_a_buy(db_session, monkeypatch):
    decision = _real_ml_swing_decision(db_session, monkeypatch, _quiet_series(), "clean")
    assert decision is not None and decision.signal == "BUY"


@pytest.mark.parametrize("factor,why", [(0.5, "a 2-for-1 split"), (2.0, "a 1-for-2 reverse split")])
def test_right_after_a_split_the_fall_and_volatility_filters_hold_the_buy_back(db_session, monkeypatch, factor, why):
    df = _quiet_series(split_at=297, factor=factor)  # the step is 3 sessions old
    decision = _real_ml_swing_decision(db_session, monkeypatch, df, f"recent{int(factor * 10)}")
    assert decision is not None and decision.signal == "HOLD", why
    assert "filtered" in decision.reason and ("volatility" in decision.reason or "falling knife" in decision.reason)


@pytest.mark.parametrize("age,expected", [(15, "HOLD"), (25, "BUY")])
def test_the_volatility_filter_forgets_a_split_between_fifteen_and_twenty_five_sessions(db_session, monkeypatch, age, expected):
    """Brackets the forgetting point: the 20-session volatility window still holds a 15-session-old step and has dropped a
    25-session-old one (the 5-session fall filter is long gone by then)."""
    decision = _real_ml_swing_decision(db_session, monkeypatch, _quiet_series(split_at=300 - age), f"age{age}")
    assert decision is not None and decision.signal == expected


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#464): v1 scoring has no corporate-action awareness. (This test replaces build_features with a fixed stand-in, so it "
    "proves the missing GUARD, not the distorted score; the distortion itself is shown in the features test above.)  The 5-day fall and 20-day volatility filters forget a split after "
    "about 20 sessions while the 200-day inputs stay distorted for up to 252; a stock split 40 sessions ago is bought on a 95% score",
)
def test_a_stock_with_a_split_step_in_its_feature_window_must_not_be_bought_on_distorted_inputs(db_session, monkeypatch):
    decision = _real_ml_swing_decision(db_session, monkeypatch, _quiet_series(split_at=260), "old")  # step 40 sessions ago
    assert decision is None or decision.signal != "BUY"


def test_the_brain_quality_gate_excuses_a_price_step_on_a_recorded_split_day_even_when_the_prices_are_unadjusted():
    """Pins the designed behaviour (also `test_brain_m01_quality.py::test_a_split_on_its_ex_date_is_not_a_spike`)."""
    bars = quality_bars(MON, edits={(-1, "close"): 50.0, (-1, "open"): 50.0, (-1, "high"): 51.0, (-1, "low"): 49.0})
    assert assess_bars("ABC", bars, MON, {MON}).fresh
    assert assess_bars("ABC", bars, MON, set()).score == pytest.approx(0.7)  # without a record the same step is penalised


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: M01 excuses any recorded split day. A step that matches the split ratio on that day means the stored prices are "
    "NOT adjusted, which is what distorts the model inputs; the gate says nothing about it",
)
def test_a_split_sized_step_on_a_recorded_split_day_should_still_be_reported_as_unadjusted_history():
    bars = quality_bars(MON, edits={(-1, "close"): 50.0, (-1, "open"): 50.0, (-1, "high"): 51.0, (-1, "low"): 49.0})
    quality = assess_bars("ABC", bars, MON, {MON})
    assert any("adjust" in issue.lower() or "split" in issue.lower() for issue in quality.issues)


def test_the_brain_excuse_list_holds_every_recorded_corporate_action_not_only_splits_and_bonuses(db_session):
    """OBSERVED: `DatedReader.action_days` (the dates M01 excuses a big move on) takes every `corporate_action` event,
    dividends included, while the split check (`services/split_check.py`) keeps only events whose text says split or
    bonus. So a dividend ex-date also excuses a 20%+ move that day. Small in practice (one day, one stock); pinned."""
    from swing_trade_ml.brain.reader import DatedReader
    from swing_trade_ml.db.models.feeds import UpcomingEvent

    db_session.add(UpcomingEvent(symbol="DIV247", kind="corporate_action", event_date=date(2026, 12, 4), detail="Dividend - Rs 5 per share"))
    db_session.add(UpcomingEvent(symbol="SPL247B", kind="corporate_action", event_date=date(2026, 12, 4), detail="Stock Split From Rs.10/- To Rs.2/-"))
    db_session.flush()
    days = DatedReader.action_days(SimpleNamespace(db=db_session))
    assert date(2026, 12, 4) in days["DIV247"] and date(2026, 12, 4) in days["SPL247B"]


# ------------------------------------------------------------------------------- (a) identity and the accounting records


def test_a_symbol_change_keeps_one_security_and_identity_never_reads_corporate_actions(db_session):
    """The meaningful checks are the rename and the old-date lookups. A split cannot create a security because
    `writer.ensure_for_instrument` never reads corporate actions (asserted at the end), so this adds a split record
    only to show nothing else moves."""
    from swing_trade_ml.db.models.market import Instrument

    inst = Instrument(instrument_token=247_001, tradingsymbol="SPL247", name="Split Limited", exchange="NSE", instrument_type="EQ", is_active=True)
    db_session.add(inst)
    db_session.flush()
    security = writer.ensure_for_instrument(db_session, inst)
    count = db_session.scalar(select(func.count()).select_from(Security))
    db_session.add(CorporateAction(instrument_id=inst.id, symbol="SPL247", kind="split", ex_date=date(2026, 12, 1), ratio_numerator=10, ratio_denominator=2, status="VERIFIED"))
    db_session.flush()
    assert writer.ensure_for_instrument(db_session, inst) == security  # the same stock after the action is recorded
    inst.tradingsymbol = "SPL247NEW"  # and after a symbol change, the same token and company
    db_session.flush()
    writer.set_symbol(db_session, security, "SPL247NEW", date(2026, 12, 2))
    assert writer.ensure_for_instrument(db_session, inst) == security
    assert resolve(db_session, token=inst.instrument_token, symbol="SPL247NEW", on_date=date(2026, 12, 3)) == security
    assert resolve(db_session, symbol="SPL247", on_date=date(2026, 11, 30)) == security  # the old symbol, for old dates
    assert db_session.scalar(select(func.count()).select_from(Security)) == count
    from pathlib import Path

    from swing_trade_ml.services.identity import writer as identity_writer

    assert "corporate_action" not in Path(identity_writer.__file__).read_text(encoding="utf8").lower()


# ------------------------------------------------------------------------------- (b) training-to-scoring consistency


def test_the_input_list_of_a_model_file_is_pinned_to_its_row_when_it_is_loaded_for_activation(db_session, tmp_path, monkeypatch):
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.ml import MLModel

    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path))
    path = registry.save_artifact("s247_pin", "v1", {"estimator": None, "feature_names": ["a", "b"]})
    row = MLModel(name="s247_pin", version="v1", algorithm="lightgbm", status="TRAINED", feature_names=["b", "a"], artifact_path=path, metrics={})
    db_session.add(row)
    db_session.flush()
    with pytest.raises(registry.ArtifactMismatchError, match="inputs differ"):  # same names, other ORDER: refused
        registry.load_model_artifact(row)
    row.feature_names = ["a", "b"]
    assert registry.load_model_artifact(row)["feature_names"] == ["a", "b"]
    row.feature_names = ["a", "b", "c"]  # a different count: refused
    with pytest.raises(registry.ArtifactMismatchError):
        registry.load_model_artifact(row)


def test_scoring_trusts_the_loaded_file_the_row_check_is_not_repeated_at_score_time(db_session, tmp_path, monkeypatch):
    """OBSERVED, not a defect: the row-versus-file input check runs when a model is activated or a lane verifies it.
    `predict._get_bundle` (the scoring path) loads and caches the file without it. Consistent by construction (the file
    carries its own input list and scoring reads that list), but a file changed after activation would not be noticed here."""
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.ml import MLModel

    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path))
    predict.clear_cache()
    path = registry.save_artifact("s247_trust", "v1", {"estimator": None, "feature_names": ["a", "b"]})
    row = MLModel(name="s247_trust", version="v1", algorithm="lightgbm", status="TRAINED", feature_names=["b", "a"], artifact_path=path, metrics={})
    db_session.add(row)
    db_session.flush()
    assert predict._get_bundle(row)["feature_names"] == ["a", "b"]  # no refusal at score time
    with pytest.raises(registry.ArtifactMismatchError):
        registry.load_model_artifact(row)
    predict.clear_cache()


def test_a_model_input_the_scoring_code_no_longer_builds_stops_that_stock_instead_of_guessing(db_session, monkeypatch):
    from swing_trade_ml.strategies import ml_swing

    df = _quiet_series()
    monkeypatch.setattr(
        ml_swing, "build_features", lambda d, *a, **k: pd.DataFrame({"other": [1.0] * len(d), "nifty_trend_regime": [1.0] * len(d)})
    )
    with pytest.raises(KeyError):  # `row[feature_names]`: the engine catches this per stock and reports it, nothing is bought
        _evaluate_with_current_stand_ins(db_session, monkeypatch, df)


def _evaluate_with_current_stand_ins(db, monkeypatch, df):
    from swing_trade_ml.strategies import ml_swing

    class Estimator:
        def predict_proba(self, x):
            return np.array([[0.05, 0.95]])

    class Scaler:
        def transform(self, x):
            return x

    model = SimpleNamespace(name="swing_classifier", version="v-test", prediction_horizon_days=15, label_kind="barrier", target_return_pct=0.08, stop_return_pct=0.04)
    empty = pd.DataFrame(columns=["ts", "close"])
    monkeypatch.setattr(ml_swing, "get_active_model", lambda db_, n: model)
    monkeypatch.setattr(ml_swing, "_get_bundle", lambda m: {"feature_names": ["f"], "scaler": Scaler(), "estimator": Estimator()})
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles", "load_market_breadth"):
        monkeypatch.setattr(ml_swing, loader, lambda *a, **k: empty)
    strat, inst = _strategy(db, name="s247_missing_input"), _instrument(db, "S247MISSING")
    return ml_swing.MLSwingStrategy(strat).evaluate(df, inst, db)


def test_an_input_that_is_not_a_number_today_gives_no_score_instead_of_a_guess(db_session, monkeypatch):
    from swing_trade_ml.strategies import ml_swing

    monkeypatch.setattr(
        ml_swing, "build_features", lambda d, *a, **k: pd.DataFrame({"f": [float("nan")] * len(d), "nifty_trend_regime": [1.0] * len(d)})
    )
    assert _evaluate_with_current_stand_ins(db_session, monkeypatch, _quiet_series()) is None


EXPECTED_INPUTS = ['sma_10_ratio', 'sma_20_ratio', 'sma_50_ratio', 'sma_200_ratio', 'ema_12_ratio', 'ema_26_ratio', 'sma_10_50_cross', 'sma_50_200_cross', 'rsi_14', 'macd', 'macd_signal', 'macd_hist', 'stoch_k', 'stoch_d', 'williams_r', 'roc_10', 'roc_20', 'atr_14_pct', 'bb_position', 'bb_width', 'volatility_20', 'volume_ratio_20', 'obv_slope', 'mfi_14', 'return_1d', 'return_5d', 'return_10d', 'return_20d', 'high_20_dist', 'low_20_dist', 'high_52w_dist', 'gap_pct', 'body_pct', 'upper_wick_pct', 'lower_wick_pct', 'days_since_52w_high', 'days_since_52w_low', 'streak', 'adx_14', 'trend_strength', 'volatility_percentile_rank', 'cmf_20', 'relative_strength_5d', 'relative_strength_20d', 'nifty_volatility_20', 'nifty_trend_regime', 'sector_relative_strength_5d', 'sector_relative_strength_20d', 'sector_trend_regime', 'vix_change_5d', 'vix_percentile_rank', 'breadth_pct_above_sma50', 'breadth_advance_pct']


def test_the_code_declares_exactly_these_fifty_three_inputs_in_this_order():
    """A model reads its inputs by position, so adding, removing, renaming or reordering one in the code is a change to
    every saved model's meaning. This literal list fails on any of those, on purpose: update it only with the owner."""
    assert list(FEATURE_COLUMNS) == EXPECTED_INPUTS and len(EXPECTED_INPUTS) == 53


# ------------------------------------------------------------------------------- (c) the h05 lane's parity check


class _Scaler:
    def __init__(self, mean, scale):
        self.mean_, self.scale_ = np.array(mean, dtype=float), np.array(scale, dtype=float)


def _window(rng, rows=4000, names=("rsi_14", "return_5d")):
    return pd.DataFrame({n: rng.normal(0.0, 1.0, rows) for n in names}).assign(obv_training=0.0)


def test_the_parity_check_passes_when_the_inputs_match_what_the_scaler_learned():
    rng = np.random.default_rng(0)
    out = h05_parity.compare_window(_window(rng), ["rsi_14", "return_5d"], _Scaler([0, 0], [1, 1]))
    assert out[proto.PRIMARY_BASIS]["ok"] is True and out[proto.PRIMARY_BASIS]["inputs_failing"] == []


def _exact(rng, rows=4000, mean=0.0, sd=1.0):
    """A sample with exactly this mean and spread (so a threshold test is not at the mercy of sampling noise)."""
    x = rng.normal(0.0, 1.0, rows)
    return (x - x.mean()) / x.std() * sd + mean


@pytest.mark.parametrize("shift,ratio", [(0.2, 1.0), (-0.2, 1.0), (0.0, 0.8), (0.0, 1.2), (0.2, 1.2)])
def test_it_passes_an_input_inside_the_thresholds(shift, ratio):
    rng = np.random.default_rng(6)
    window = pd.DataFrame({"rsi_14": _exact(rng), "return_5d": _exact(rng, mean=shift, sd=ratio), "obv_training": 0.0})
    out = h05_parity.compare_window(window, ["rsi_14", "return_5d"], _Scaler([0, 0], [1, 1]))[proto.PRIMARY_BASIS]
    assert out["ok"] is True and out["inputs_failing"] == []


@pytest.mark.parametrize("shift,ratio", [(0.3, 1.0), (0.0, 0.7), (0.0, 1.3)])
def test_it_flags_just_outside_the_thresholds(shift, ratio):
    rng = np.random.default_rng(7)
    window = pd.DataFrame({"rsi_14": _exact(rng), "return_5d": _exact(rng, mean=shift, sd=ratio), "obv_training": 0.0})
    out = h05_parity.compare_window(window, ["rsi_14", "return_5d"], _Scaler([0, 0], [1, 1]))[proto.PRIMARY_BASIS]
    assert out["ok"] is False and [f["input"] for f in out["inputs_failing"]] == ["return_5d"]


def test_the_primary_basis_swaps_obv_slope_for_its_training_formula_so_only_the_production_basis_shows_the_skew():
    """The PRIMARY basis replaces `obv_slope` by `obv_training` (`h05_parity.py:46`), so a primary "ok" says nothing about
    how production serves obv_slope. The production-path basis (`proto.DIAGNOSTIC_BASIS`) is where a skew would show."""
    rng = np.random.default_rng(8)
    window = pd.DataFrame(
        {"rsi_14": _exact(rng), "obv_slope": _exact(rng, mean=1.0), "obv_training": _exact(rng)}  # served 1 sd away
    )
    out = h05_parity.compare_window(window, ["rsi_14", "obv_slope"], _Scaler([0, 0], [1, 1]))
    assert out[proto.PRIMARY_BASIS]["ok"] is True
    assert out[proto.DIAGNOSTIC_BASIS]["ok"] is False
    assert [f["input"] for f in out[proto.DIAGNOSTIC_BASIS]["inputs_failing"]] == ["obv_slope"]


@pytest.mark.parametrize("shift", [0.3, -0.5, 1.0])
def test_it_flags_an_input_whose_average_has_moved_more_than_a_quarter_of_a_standard_deviation(shift):
    rng = np.random.default_rng(1)
    window = _window(rng)
    window["return_5d"] += shift
    out = h05_parity.compare_window(window, ["rsi_14", "return_5d"], _Scaler([0, 0], [1, 1]))[proto.PRIMARY_BASIS]
    assert out["ok"] is False and [f["input"] for f in out["inputs_failing"]] == ["return_5d"]


@pytest.mark.parametrize("ratio", [0.5, 1.6])
def test_it_flags_an_input_whose_spread_is_outside_the_band(ratio):
    rng = np.random.default_rng(2)
    window = _window(rng)
    window["rsi_14"] *= ratio
    out = h05_parity.compare_window(window, ["rsi_14", "return_5d"], _Scaler([0, 0], [1, 1]))[proto.PRIMARY_BASIS]
    assert out["ok"] is False and [f["input"] for f in out["inputs_failing"]] == ["rsi_14"]


def test_what_the_parity_check_cannot_see_a_wrong_input_with_the_right_average_and_spread():
    """OBSERVED LIMIT, by design (it compares each input's average and spread, nothing row by row): an input whose values
    are scrambled across stocks and days, or built from the wrong stock, keeps its average and spread and passes."""
    rng = np.random.default_rng(3)
    window = _window(rng)
    scrambled = window.copy()
    scrambled["return_5d"] = rng.permutation(scrambled["return_5d"].to_numpy())
    assert not np.allclose(scrambled["return_5d"], window["return_5d"])
    out = h05_parity.compare_window(scrambled, ["rsi_14", "return_5d"], _Scaler([0, 0], [1, 1]))[proto.PRIMARY_BASIS]
    assert out["ok"] is True


def test_what_the_parity_check_cannot_see_a_split_that_the_training_data_already_contained():
    """OBSERVED LIMIT: both sides are built from the same stored candles, so a step the model was trained on (the scaler
    learned the step's outliers) is reproduced exactly and reported as parity. It checks consistency, not correctness."""
    rng = np.random.default_rng(4)
    clean = rng.normal(0.0, 0.02, 4000)
    contaminated = clean.copy()
    contaminated[::400] = -0.5  # ten unadjusted 2-for-1 steps inside the training window
    scaler = _Scaler([contaminated.mean()], [contaminated.std()])  # what the scaler would have learned from it
    window = pd.DataFrame({"return_1d": contaminated, "obv_training": 0.0})
    out = h05_parity.compare_window(window, ["return_1d"], scaler)[proto.PRIMARY_BASIS]
    assert out["ok"] is True


def test_the_parity_check_reads_the_input_order_from_the_current_code():
    rng = np.random.default_rng(5)
    names = ["return_5d", "rsi_14"]  # the opposite of the code's order (rsi_14 comes first)
    window = _window(rng, names=tuple(names))
    out = h05_parity.compare_window(window, names, _Scaler([0, 0], [1, 1]))
    assert out["order_matches_code"] is False
    assert h05_parity.compare_window(_window(rng), ["rsi_14", "return_5d"], _Scaler([0, 0], [1, 1]))["order_matches_code"] is True
