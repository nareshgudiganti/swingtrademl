"""Row reconciliation for the sector experiments: every removed row is counted once, in a stated order."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from swing_trade_ml.ml import sector_reconcile as rc

START = date(2022, 1, 3)


def _dates(n):
    return [START + timedelta(days=i) for i in range(n)]


def _hit(dates, p, event_id, kind="feature"):
    return {"decision_date": dates[p].isoformat(), "event_id": event_id, "window_type": kind}


def test_every_row_has_exactly_one_stage_and_totals_add_up():
    n, h, warm = 100, 5, 10
    dates = _dates(n)
    feat_ok = np.ones(n, dtype=bool)
    feat_ok[20:22] = False  # existing-feature gaps
    sec_ok = np.ones(n, dtype=bool)
    sec_ok[40:45] = False
    hits = [_hit(dates, p, "A:1") for p in range(30, 36)]
    r = rc.reconcile_stock(dates, hits, feat_ok, sec_ok, horizon=h, min_history=warm)
    c = r.counts
    assert c["raw"] == n
    assert c["warm_up"] == warm and c["label_incomplete"] == h
    assert c["event"] == 6 and c["existing_gap"] == 2 and c["sector_gap"] == 5
    assert c["final"] == n - warm - h - 6 - 2 - 5
    assert sum(r.stage.value_counts().drop("final", errors="ignore")) + c["final"] == n


def test_overlap_attributed_to_first_reason_and_listed():
    n, h, warm = 100, 5, 10
    dates = _dates(n)
    feat_ok = np.ones(n, dtype=bool)
    sec_ok = np.ones(n, dtype=bool)
    sec_ok[32:38] = False  # overlaps the event window 30..35 on 32..35 (4 rows) and extends to 36, 37
    hits = [_hit(dates, p, "A:1") for p in range(30, 36)]
    r = rc.reconcile_stock(dates, hits, feat_ok, sec_ok, horizon=h, min_history=warm)
    assert r.counts["event"] == 6  # the first reason wins
    assert r.counts["sector_gap"] == 2  # only 36, 37 are new
    assert r.overlap[("event", "sector_gap")] == 4
    # a sector-gap row inside the event window is NOT counted again
    assert r.counts["raw"] - r.counts["final"] == 10 + 5 + 6 + 2


def test_warmup_and_end_rows_are_not_event_rows():
    n, h, warm = 60, 5, 20
    dates = _dates(n)
    hits = [_hit(dates, p, "A:1") for p in range(10, 25)]  # 10..19 are inside warm-up
    r = rc.reconcile_stock(
        dates, [x for x in hits if True], np.ones(n, bool), None, horizon=h, min_history=warm
    )
    # event hits handed in by the exclusion report are already limited to buildable rows; ones that are not are
    # still attributed to the earlier stage (warm-up), never twice
    assert r.counts["warm_up"] == 20
    assert r.counts["event"] == 5  # 20..24
    assert r.overlap[("warm_up", "event")] == 10


def test_sector_not_required_means_no_sector_stage():
    n = 50
    dates = _dates(n)
    r = rc.reconcile_stock(dates, [], np.ones(n, bool), None, horizon=5, min_history=10)
    assert r.counts["sector_gap"] == 0
    assert r.counts["final"] == n - 15


def test_two_events_attribute_to_earlier_event_and_list_second():
    n = 100
    dates = _dates(n)
    hits = [_hit(dates, p, "A:early") for p in range(30, 40)] + [
        _hit(dates, p, "A:late") for p in range(35, 45)
    ]
    r = rc.reconcile_stock(dates, hits, np.ones(n, bool), None, horizon=5, min_history=10)
    assert r.counts["event"] == 15
    assert r.event_rows == {"A:early": 10, "A:late": 5}
    assert r.event_overlap == {("A:early", "A:late"): 5}


def test_final_keys_are_symbol_pipe_date_and_hash_matches_report_hash():
    from swing_trade_ml.ml import exclusion_report as er

    n = 30
    dates = _dates(n)
    r = rc.reconcile_stock(dates, [], np.ones(n, bool), None, horizon=5, min_history=10)
    keys = r.final_keys("AAA")
    assert keys[0] == f"AAA|{dates[10].isoformat()}" and len(keys) == 15
    assert rc.keys_sha256(keys) == er.dataset_hash(keys)


def test_cross_universe_matched_baseline_is_subset_check():
    a = ["A|2024-01-01", "A|2024-01-02", "B|2024-01-01"]
    b = ["A|2024-01-01", "B|2024-01-01"]
    assert rc.is_subset(b, a) and not rc.is_subset(a, b)
