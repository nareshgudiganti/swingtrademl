"""Pure tests for the price change detector (no DB, no network)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from swing_trade_ml.services import price_change_detector as pcd


def days(n: int, start: date = date(2026, 1, 5)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars(closes, vols=None, start=date(2026, 1, 5)):
    ds = days(len(closes), start)
    vols = vols or [1000] * len(closes)
    return [
        {"date": d.isoformat(), "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": v}
        for d, c, v in zip(ds, closes, vols)
    ]


def scaled(rows, factor, upto):
    out = []
    for i, r in enumerate(rows):
        r = dict(r)
        if i < upto:
            for k in ("open", "high", "low", "close"):
                r[k] = r[k] * factor
        out.append(r)
    return out


BASE = [100 + (i % 3) for i in range(30)]


def test_unchanged_window_no_findings():
    b = bars(BASE)
    r = pcd.compare_windows("X", b, b)
    assert not r.restatement and r.pattern == "unchanged" and r.diffs == ()


def test_uniform_scale_restatement_with_factor_and_change_date():
    b = bars(BASE)
    f = scaled(b, 0.8649, 20)
    r = pcd.compare_windows("X", b, f)
    assert r.restatement and r.pattern == "uniform_scale"
    assert r.factor == pytest.approx(0.8649, rel=1e-6)
    assert r.change_date == days(30)[20]


def test_reliance_coa_step_0_9532():
    b = bars(BASE)
    r = pcd.compare_windows("RELIANCE", b, scaled(b, 0.9532, 12))
    assert r.pattern == "uniform_scale" and r.factor == pytest.approx(0.9532, rel=1e-6)
    assert r.change_date == days(30)[12]


def test_split_one_to_two_pattern():
    b = bars(BASE, vols=[1000] * 30)
    r = pcd.compare_windows("S", b, scaled(b, 0.5, 15))
    assert r.restatement and r.pattern == "uniform_scale" and r.factor == pytest.approx(0.5)
    rep = pcd.build_report("t", [r])
    assert rep.restatements[0]["factor"] == pytest.approx(0.5)
    assert "do not bulk-scrape NSE" in rep.text and "owner decision" in rep.text


def test_scattered_differences():
    b = bars(BASE)
    f = [dict(r) for r in b]
    f[3]["close"] *= 1.05
    f[17]["close"] *= 0.9
    r = pcd.compare_windows("X", b, f)
    assert r.restatement and r.pattern == "scattered" and r.factor is None


def test_small_difference_not_restatement():
    b = bars(BASE)
    f = [dict(r) for r in b]
    f[5]["close"] *= 1.002
    r = pcd.compare_windows("X", b, f)
    assert not r.restatement and len(r.diffs) == 1


def test_missing_and_extra_dates():
    b = bars(BASE)
    f = b[:10] + b[12:]
    r = pcd.compare_windows("X", b, f)
    assert r.pattern == "missing_or_extra_dates" and len(r.missing_in_fetched) == 2
    r2 = pcd.compare_windows("X", f, b)
    assert len(r2.extra_in_fetched) == 2
    rep = pcd.build_report("t", [r])
    assert rep.other_differences and not rep.restatements


@pytest.mark.parametrize(
    "a,b", [(None, None), ([], []), ([], bars(BASE)), (bars(BASE), []), ([{"junk": 1}], [{"date": "bad"}])]
)
def test_empty_or_bad_inputs_never_raise(a, b):
    r = pcd.compare_windows("X", a, b)
    assert not r.restatement
    assert pcd.detect_signatures("X", a) == []
    pcd.build_report("t", [r])


def test_news_move_is_large_move_not_restatement():
    closes = [100.0] * 30 + [125.0, 126.0]
    vols = [1000] * 30 + [8000, 3000]
    b = bars(closes, vols)
    assert not pcd.compare_windows("N", b, b).restatement
    kinds = [s.kind for s in pcd.detect_signatures("N", b)]
    assert kinds == ["large_move"]
    rep = pcd.build_report("t", [pcd.compare_windows("N", b, b)], pcd.detect_signatures("N", b))
    assert "single-announcement lookup" in rep.text


def test_unadjusted_split_signature_flagged():
    closes = [100.0] * 30 + [50.0, 50.0]
    vols = [1000] * 30 + [2000, 2000]  # volume doubles when price halves
    kinds = {s.kind for s in pcd.detect_signatures("S", bars(closes, vols))}
    assert "split_ratio_signature" in kinds


def test_price_step_low_volume_flagged_and_exclusion():
    closes = [100.0] * 30 + [90.0, 90.0]
    b = bars(closes)
    f = pcd.detect_signatures("D", b)
    assert [x.kind for x in f] == ["price_step_low_volume"]
    assert pcd.detect_signatures("D", b, exclude=[f[0].date]) == []


def test_high_volume_normal_move_not_flagged():
    closes = [100.0] * 30 + [108.0]
    b = bars(closes, [1000] * 30 + [5000])
    assert pcd.detect_signatures("M", b) == []


def test_rotating_slice_deterministic_and_covers_universe_in_month():
    universe = [f"S{i}" for i in range(200)]
    start = date(2026, 3, 2)
    assert pcd.rotating_slice(universe, start) == pcd.rotating_slice(universe, start)
    seen: dict[str, int] = {}
    d, wk = start, 0
    while wk < 20:
        if d.weekday() < 5:
            for s in pcd.rotating_slice(universe, d):
                seen[s] = seen.get(s, 0) + 1
            wk += 1
        d += timedelta(days=1)
    assert set(seen) == set(universe) and set(seen.values()) == {1}


def test_windows_helpers():
    td = days(300)
    assert pcd.overlap_window(td) == (td[-10], td[-1])
    assert pcd.older_window(td) == (td[-260], td[-1])
    assert pcd.overlap_window([]) is None


class _NoWrite:
    """Fake store: any write attempt fails the test."""

    def __init__(self, rows):
        self.rows = rows

    def load(self, sym, a, b):
        return self.rows[sym]

    def __getattr__(self, name):
        if name.startswith(("write", "upsert", "insert", "update", "delete", "commit", "queue", "refetch")):
            raise AssertionError(f"detector called write function {name}")
        raise AttributeError(name)


def test_job_never_writes_and_reports(tmp_path):
    b = bars(BASE)
    store = _NoWrite({"A": b, "B": b})
    fetched = {"A": scaled(b, 0.8649, 20), "B": b}
    td = days(30)
    rep = pcd.run_detection_job(["A", "B"], td[-1], td, store.load, lambda s, a, c: fetched[s], cycle=1)
    assert [r["symbol"] for r in rep.restatements] == ["A"]
    log = tmp_path / "log.jsonl"
    pcd.append_jsonl(rep, str(log))
    assert json.loads(log.read_text().splitlines()[0])["symbols_checked"] == 2


def test_job_survives_fetch_failure():
    b = bars(BASE)

    def boom(*a):
        raise RuntimeError("vendor down")

    rep = pcd.run_detection_job(["A"], date(2026, 2, 2), days(30), lambda *a: b, boom)
    assert rep.restatements == []


def test_module_has_no_db_imports():
    src = open(pcd.__file__, encoding="utf-8").read()
    assert "sqlalchemy" not in src and "db.models" not in src


def test_offline_cli(tmp_path, capsys):
    b = bars(BASE)
    sp, fp = tmp_path / "s.json", tmp_path / "f.json"
    sp.write_text(json.dumps({"X": b}))
    fp.write_text(json.dumps({"X": scaled(b, 0.5, 15)}))
    assert pcd.main(["--offline", str(sp), str(fp)]) == 0
    out = capsys.readouterr().out
    assert "X" in out and "0.5000" in out and "No data was changed" in out
