from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.ml.dataset import chronological_split
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_label
from swing_trade_ml.services import engine, execution
from swing_trade_ml.strategies.base import SignalDecision


def test_long_term_real_feature_inference(monkeypatch):
    from swing_trade_ml.strategies import long_term_value as lt

    rng = np.random.default_rng(42)
    close = 100 * np.cumprod(1 + rng.normal(0.001, 0.015, 400))
    df = pd.DataFrame(dict(ts=pd.date_range('2024-01-01', periods=400, tz='UTC'),
                           open=close, close=close, high=close * 1.02,
                           low=close * .98, volume=rng.integers(200_000, 900_000, 400)))
    breadth = pd.DataFrame(dict(ts=df.ts, breadth_pct_above_sma50=.6, breadth_advance_pct=.5))
    for name in ('load_index_candles', 'load_sector_candles', 'load_vix_candles', 'load_market_breadth'):
        def load(*args, _name=name, **kwargs):
            assert kwargs['upto'] == df.ts.max()
            return breadth if _name == 'load_market_breadth' else df
        monkeypatch.setattr(lt, name, load)
    monkeypatch.setattr(lt, 'get_active_model', lambda *a: SimpleNamespace(name='lt', version=1))
    scaler = Mock()
    scaler.transform.side_effect = lambda x: x
    estimator = Mock()
    estimator.predict_proba.return_value = np.array([[.2, .8]])
    monkeypatch.setattr(lt, '_get_bundle', lambda *a: dict(
        feature_names=FEATURE_COLUMNS, scaler=scaler, estimator=estimator))
    strategy = lt.LongTermValueStrategy(Strategy(name='lt', strategy_type='long_term_value', params={}))
    decision = strategy.evaluate(df, SimpleNamespace(tradingsymbol='TCS'), None)
    assert decision.signal == SignalType.BUY
    assert np.isfinite(scaler.transform.call_args.args[0]).all()
    assert scaler.transform.call_args.args[0].shape == (1, len(FEATURE_COLUMNS))


def test_label_end_comes_from_original_bars():
    df = pd.DataFrame(dict(ts=pd.to_datetime(['2024-01-01', '2024-01-03', '2024-01-08']),
                           close=[100]*3, high=[101]*3, low=[99]*3))
    labelled = build_label(df, horizon_days=2)
    assert labelled.iloc[0].label_end_ts == df.iloc[2].ts
    assert 'label_end_ts' not in FEATURE_COLUMNS


def test_split_keeps_dates_together_and_purges_labels():
    dates = pd.date_range('2024-01-01', periods=20, tz='UTC')
    df = pd.DataFrame(dict(ts=dates.repeat(2), label_end_ts=(dates + pd.Timedelta(days=3)).repeat(2)))
    train, test = chronological_split(df.sample(frac=1, random_state=42), .2)
    assert set(train.ts).isdisjoint(test.ts)
    assert (train.label_end_ts < test.ts.min()).all()
    assert test.groupby('ts').size().eq(2).all()
    assert train.attrs['split']['purged_rows'] == 6


@pytest.mark.parametrize('fraction', [0, 1, -.1, 1.1, float('nan')])
def test_invalid_split_rejected(fraction):
    with pytest.raises(ValueError, match='test_size'):
        chronological_split(pd.DataFrame(), fraction)


def test_empty_after_purge_rejected():
    dates = pd.date_range('2024-01-01', periods=5)
    with pytest.raises(ValueError, match='purging'):
        chronological_split(pd.DataFrame(dict(ts=dates, label_end_ts=dates + pd.Timedelta(days=20))))


def test_single_class_training_rejected(monkeypatch):
    from swing_trade_ml.ml import train as training
    dates = pd.date_range('2024-01-01', periods=20)
    df = pd.DataFrame(dict(ts=dates, label_end_ts=dates, target=0))
    monkeypatch.setattr(training, 'build_training_dataset', lambda *a, **kw: df)
    with pytest.raises(ValueError, match='one class'):
        training.train_model(None)


def test_long_term_api_defaults_and_rejects_auto(client, db_session):
    headers = {'X-API-Key': 'test-api-key'}
    body = dict(name='lt-api', strategy_type='long_term_value')
    response = client.post('/api/v1/strategies', json=body, headers=headers)
    assert response.status_code == 201
    assert response.json()['execution_mode'] == 'advisory'
    sid = response.json()['id']
    assert client.patch(f'/api/v1/strategies/{sid}', json={'execution_mode': 'auto'},
                        headers=headers).status_code == 422
    body.update(name='lt-auto', execution_mode='auto')
    assert client.post('/api/v1/strategies', json=body, headers=headers).status_code == 422


def test_long_term_direct_orders_blocked_before_io():
    strategy = Strategy(name='lt', strategy_type='long_term_value', execution_mode='auto')
    with pytest.raises(ValueError, match='advisory'):
        execution.open_position(None, strategy, None, None, 1)
    with pytest.raises(ValueError, match='advisory'):
        execution.close_position(None, SimpleNamespace(strategy=strategy), 100, 'MANUAL')


@pytest.mark.parametrize('signal', [SignalType.BUY, SignalType.EXIT])
def test_legacy_long_term_auto_row_routes_to_advisory(monkeypatch, signal):
    strategy = Strategy(id=1, name='lt', mode='paper', strategy_type='long_term_value', execution_mode='auto')
    db = Mock()
    db.execute.return_value.scalars.return_value.all.return_value = (
        [SimpleNamespace()] if signal == SignalType.EXIT else [])
    monkeypatch.setattr(execution, '_check_confidence_decay', lambda *a: None)
    monkeypatch.setattr(execution, 'portfolio_value_and_cash', lambda *a: (10000, 10000))
    monkeypatch.setattr(execution.risk, 'check_entry', lambda **kw: SimpleNamespace(allowed=True, quantity=1))
    record = SimpleNamespace(advisory_only=False)
    monkeypatch.setattr(execution, 'record_signal', lambda *a: record)
    monkeypatch.setattr(execution, '_advisory_entry_message', lambda *a: '')
    monkeypatch.setattr(execution, '_advisory_exit_message', lambda *a: '')
    monkeypatch.setattr(execution.notifier, 'send_sync', lambda *a: None)
    broker_entry, broker_exit = Mock(), Mock()
    monkeypatch.setattr(execution, 'open_position', broker_entry)
    monkeypatch.setattr(execution, 'close_position', broker_exit)
    execution.process_decision(db, strategy, SimpleNamespace(id=1), SignalDecision(signal, 100, .8))
    assert record.advisory_only
    broker_entry.assert_not_called()
    broker_exit.assert_not_called()


@pytest.mark.parametrize('confirmed_exit', [True, False])
def test_scan_exits_first_then_stable_rank_in_strategy_mode(monkeypatch, confirmed_exit):
    strategy = Strategy(id=1, name='scan', mode='live', strategy_type='ml_swing',
                        execution_mode='advisory', max_positions=2, max_daily_buys=None)
    items = [SimpleNamespace(id=i, tradingsymbol=str(i)) for i in range(4)]
    decisions = [SignalDecision(SignalType.BUY, 100, .6), SignalDecision(SignalType.EXIT, 100, .8),
                 SignalDecision(SignalType.BUY, 100, .9), SignalDecision(SignalType.BUY, 100, .9)]
    impl = SimpleNamespace(min_bars_required=lambda: 1, evaluate=lambda df, i, db: decisions[i.id])
    monkeypatch.setattr(engine, 'get_strategy', lambda *a: impl)
    monkeypatch.setattr(engine, 'eligible_instruments', lambda *a: items)
    monkeypatch.setattr(engine, 'load_candles', lambda *a, **kw: pd.DataFrame({'close': [100]}))
    calls = []
    def count(db, mode):
        assert mode == 'live'
        assert calls[0][0] == 1
        return 0 if confirmed_exit else 1
    monkeypatch.setattr(engine.risk, 'open_position_count', count)
    def process(db, strategy, instrument, decision, ranked_out_reason=None):
        calls.append((instrument.id, ranked_out_reason))
        return SimpleNamespace(was_executed=False)
    monkeypatch.setattr(engine, 'process_decision', process)
    assert not engine.run_strategy(Mock(), strategy).errors
    assert [i for i, _ in calls] == [1, 2, 3, 0]
    assert calls[1][1] is None
    assert (calls[2][1] is None) == confirmed_exit
    assert calls[3][1] is not None


def test_mismatched_direct_scan_rejected(client, db_session):
    row = Strategy(name='wrong-mode', strategy_type='ml_swing', mode='live', execution_mode='auto')
    db_session.add(row)
    db_session.commit()
    result = client.post(f'/api/v1/strategies/{row.id}/scan', headers={'X-API-Key': 'test-api-key'})
    assert result.status_code == 422


def test_advisory_migration_preserves_mode_and_downgrade(monkeypatch, db_session):
    row = Strategy(name='lt-migration', strategy_type='long_term_value', mode='live', execution_mode='auto')
    other = Strategy(name='swing-migration', strategy_type='ml_swing', mode='paper', execution_mode='auto')
    db_session.add_all([row, other])
    db_session.commit()
    path = Path(__file__).parents[1] / 'alembic/versions/20260915_1800_long_term_advisory.py'
    spec = spec_from_file_location('advisory_migration', path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    from sqlalchemy import text
    monkeypatch.setattr(migration, 'op', SimpleNamespace(execute=lambda sql: db_session.execute(text(sql))))
    migration.upgrade()
    migration.downgrade()
    db_session.refresh(row)
    db_session.refresh(other)
    assert (row.mode, row.execution_mode) == ('live', 'advisory')
    assert other.execution_mode == 'auto'
