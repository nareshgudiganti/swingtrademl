"""Exclusion report: window arithmetic, categories, hash stability. Pure; no database."""

from __future__ import annotations

from datetime import date, timedelta

from swing_trade_ml.ml import exclusion_report as er

START = date(2022, 1, 3)


def _dates(n):
    return [START + timedelta(days=i) for i in range(n)]  # calendar days are fine as "sessions" here


def _ev(stock, d, category, eid=None):
    return er.Event(eid or f"{stock}:{d}", stock, d, "test", "VERIFIED", True, True, category)


def test_window_arithmetic_feature_and_label():
    dates = _dates(1000)
    pol = er.Policy(horizon=5, feature_lookback=10, min_history=0)
    e = 500
    ev = _ev("AAA", dates[e].isoformat(), er.EXCLUDE)
    hits = er.excluded_rows({"AAA": dates}, [ev], pol)
    feat = sorted(h["decision_date"] for h in hits if h["window_type"] == "feature")
    lab = sorted(h["decision_date"] for h in hits if h["window_type"] == "label")
    assert feat[0] == dates[e].isoformat() and feat[-1] == dates[e + 10].isoformat() and len(feat) == 11
    assert lab[0] == dates[e - 5].isoformat() and lab[-1] == dates[e - 1].isoformat() and len(lab) == 5


def test_event_on_non_session_maps_to_next_session():
    dates = [d for d in _dates(1000) if d.weekday() < 5]
    sat = next(d for d in _dates(1000) if d.weekday() == 5 and d > dates[300])
    pol = er.Policy(horizon=2, feature_lookback=1, min_history=0)
    hits = er.excluded_rows({"A": dates}, [_ev("A", sat.isoformat(), er.EXCLUDE)], pol)
    first_after = min(d for d in dates if d >= sat)
    assert min(h["decision_date"] for h in hits if h["window_type"] == "feature") == first_after.isoformat()


def test_genuine_and_provisional_not_removed_in_base_but_provisional_in_sensitivity():
    dates = _dates(1000)
    pol = er.Policy(horizon=5, feature_lookback=10, min_history=0)
    evs = [
        _ev("A", dates[300].isoformat(), er.RETAIN_GENUINE),
        _ev("A", dates[600].isoformat(), er.PROVISIONAL),
    ]
    assert er.excluded_rows({"A": dates}, evs, pol) == []
    prov = er.Policy(horizon=5, feature_lookback=10, min_history=0, include_provisional=True)
    assert len(er.excluded_rows({"A": dates}, evs, prov)) > 0


def test_pending_is_kept_in_exclusion_list_and_flagged():
    row = {"stock": "HINDUNILVR", "date": "2025-12-05", "status": "VERIFIED", "mechanical_step": "True"}
    assert er.classify(row) == er.PENDING
    row2 = {"stock": "BAJAJELEC", "date": "2023-09-14", "status": "PARTIALLY", "mechanical_step": "True"}
    assert er.classify(row2) == er.PENDING


def test_classify_owner_decisions():
    base = {"date": "2023-01-27", "status": "UNVERIFIED", "mechanical_step": "False"}
    assert er.classify({**base, "stock": "ADANIENT"}) == er.RETAIN_GENUINE
    assert er.classify({**base, "stock": "SBIN"}) == er.PROVISIONAL
    assert er.classify({**base, "stock": "SBIN", "status": "GENUINE MOVE (x)"}) == er.RETAIN_GENUINE
    assert (
        er.classify({**base, "stock": "RELIANCE", "mechanical_step": "True", "status": "VERIFIED"})
        == er.EXCLUDE
    )


def test_warmup_and_label_cutoff_not_counted_as_exclusions():
    dates = _dates(400)
    pol = er.Policy(horizon=5, feature_lookback=10, min_history=252)
    assert len(er.base_rows(dates, pol)) == 400 - 5 - 252
    # event inside warm-up: its label window rows lie before min_history -> nothing excluded
    assert er.excluded_rows({"A": dates}, [_ev("A", dates[100].isoformat(), er.EXCLUDE)], pol) == []


def test_hash_is_order_independent_and_changes_with_rows():
    a = er.dataset_hash(["A|2024-01-01", "B|2024-01-02"])
    assert a == er.dataset_hash(["B|2024-01-02", "A|2024-01-01"])
    assert a != er.dataset_hash(["A|2024-01-01"])


def test_summary_counts_and_sensitivity_monotone():
    dates = _dates(1500)
    evs = [_ev("A", dates[800].isoformat(), er.EXCLUDE), _ev("A", dates[1000].isoformat(), er.PROVISIONAL)]
    table = er.sensitivity({"A": dates}, evs, (5, 10), lookbacks=(63, 252))
    by = {(r["horizon"], r["feature_lookback"], r["removes"]): r["rows_lost"] for r in table}
    assert by[(5, 252, "verified+pending (base)")] >= by[(5, 63, "verified+pending (base)")]
    assert by[(10, 252, "verified+pending (base)")] >= by[(5, 252, "verified+pending (base)")]
    assert by[(5, 252, "verified+pending+provisional")] > by[(5, 252, "verified+pending (base)")]
    s = er.summarise({"A": dates}, evs, er.Policy(horizon=5))
    assert s["buildable_rows"] - s["excluded_unique_rows"] == s["retained_rows"]
