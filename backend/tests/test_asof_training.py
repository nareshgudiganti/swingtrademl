from __future__ import annotations

from datetime import date

import pandas as pd

from swing_trade_ml.ml import dataset as ds
from swing_trade_ml.ml.asof import asof_cutoff
from swing_trade_ml.ml.dataset import cutoff_timestamp


def test_cutoff_timestamp_is_the_end_of_that_ist_day():
    ts = cutoff_timestamp(date(2026, 7, 10))
    assert ts.tzinfo is not None
    assert ts == pd.Timestamp("2026-07-10 23:59:00", tz="Asia/Kolkata")


def test_apply_cutoff_drops_rows_whose_label_ended_after_it():
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-07-01", "2026-07-08", "2026-07-09"], utc=True),
            "label_end_ts": pd.to_datetime(["2026-07-09", "2026-07-10", "2026-07-30"], utc=True),
            "target": [1, 0, 1],
        }
    )
    kept = ds.apply_cutoff(frame, date(2026, 7, 10))
    assert list(kept["target"]) == [1, 0]  # the row whose outcome landed on 30 July is gone


def test_apply_cutoff_without_a_cutoff_changes_nothing():
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-07-01"], utc=True),
            "label_end_ts": pd.to_datetime(["2030-01-01"], utc=True),
        }
    )
    assert len(ds.apply_cutoff(frame, None)) == 1


class _Model:
    def __init__(self, metrics):
        self.metrics = metrics


def test_asof_cutoff_reads_the_recorded_date_or_none():
    assert asof_cutoff(_Model({"asof_cutoff": "2026-07-10"})) == date(2026, 7, 10)
    assert asof_cutoff(_Model({})) is None
    assert asof_cutoff(_Model(None)) is None
