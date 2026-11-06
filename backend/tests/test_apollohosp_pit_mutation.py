"""Point-in-time FUTURE-DATA MUTATION check for the five restored APOLLOHOSP rows (SX5 and SX10).

Decision days D: 2022-10-27, 2022-11-01, 2022-11-02, 2022-11-03, 2022-11-04. For each D and each horizon (5, 10):

  A. "after D": scramble every price / volume / index (NIFTY 50 and all 15 sector indices) / VIX / breadth value
     dated AFTER D, rebuild with the batch assembler: the 56 inputs of D and of every earlier row are bit-identical.
     Power: the inputs of the row at the n-th next trading session (n = 1, 2, 5, 10, 20, 60) DO change.
  B. "cut at D+n": scramble everything dated after the n-th next session: every row up to that session (D
     included) is bit-identical; the row of the session after the cut changes (power).
  C. Mirror: the as-of builder (assemble_asof_row) at D equals the batch row at D, with the full data, with all
     data after D removed, and with all data after D scrambled.

The real-data tests read ONE stock + indices with SELECT only (read-only transaction, 5 s connect timeout) and
SKIP when the local database is unreachable. A synthetic twin of the same battery always runs. Fits no model.

  python tests/test_apollohosp_pit_mutation.py --write-md <path>   # regenerate the evidence table (needs the DB)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_research as sr

SYMBOL = "APOLLOHOSP"
DECISION_DAYS = ("2022-10-27", "2022-11-01", "2022-11-02", "2022-11-03", "2022-11-04")
HORIZONS = (5, 10)
SESSIONS = (1, 2, 5, 10, 20, 60)
COLS = list(sr.RESEARCH_COLUMNS)


# ---------------------------------------------------------------------------------------------- helpers
def _spec(h: int) -> sr.DatasetSpec:
    cand = "SX5" if h == 5 else "SX10"
    kind, target, stop = sr.PROTOCOL_LABELS[cand]
    return sr.DatasetSpec(
        candidate=cand,
        symbols=(SYMBOL,),
        horizon_days=h,
        target_return=target,
        stop_return=stop,
        label_kind=kind,
        data_cutoff=date(2026, 12, 31),
    )  # NO exclusions: the five restored rows and their neighbours must all be present


def _dates(df: pd.DataFrame) -> pd.Series:
    return sr._ist_date(df["ts"])


def _scramble_frame(df: pd.DataFrame, after: pd.Timestamp, rng: np.random.Generator) -> pd.DataFrame:
    out = df.copy()
    m = (_dates(out) > after).to_numpy()
    n = int(m.sum())
    if n == 0:
        return out
    if "close" in out.columns:  # prices: one random factor per bar (keeps open/high/low/close consistent)
        f = rng.uniform(0.5, 2.0, n)
        for c in ("open", "high", "low", "close"):
            if c in out.columns:
                out.loc[m, c] = out.loc[m, c].to_numpy(dtype="float64") * f
    if "volume" in out.columns:
        out.loc[m, "volume"] = out.loc[m, "volume"].to_numpy(dtype="float64") * rng.uniform(0.2, 5.0, n)
    for c in ("breadth_pct_above_sma50", "breadth_advance_pct"):
        if c in out.columns:
            out[c] = out[c].astype("float64")
            out.loc[m, c] = rng.uniform(0.0, 1.0, n)
    return out


def scramble_after(inputs: sr.ResearchInputs, after: pd.Timestamp, seed: int = 123) -> sr.ResearchInputs:
    """Every stock, NIFTY 50, sector-index, VIX and breadth value dated (IST) after `after` is replaced."""
    rng = np.random.default_rng(seed)
    return sr.ResearchInputs(
        raw={k: _scramble_frame(v, after, rng) for k, v in sorted(inputs.raw.items())},
        index_df=_scramble_frame(inputs.index_df, after, rng),
        index_frames={k: _scramble_frame(v, after, rng) for k, v in sorted(inputs.index_frames.items())},
        vix_df=_scramble_frame(inputs.vix_df, after, rng),
        breadth_df=_scramble_frame(inputs.breadth_df, after, rng),
        source=inputs.source,
    )


def truncate_after(inputs: sr.ResearchInputs, day: pd.Timestamp) -> sr.ResearchInputs:
    def cut(d: pd.DataFrame) -> pd.DataFrame:
        return d[_dates(d) <= day].reset_index(drop=True)

    return sr.ResearchInputs(
        raw={k: cut(v) for k, v in inputs.raw.items()},
        index_df=cut(inputs.index_df),
        index_frames={k: cut(v) for k, v in inputs.index_frames.items()},
        vix_df=cut(inputs.vix_df),
        breadth_df=cut(inputs.breadth_df),
        source=inputs.source,
    )


def sessions_after(inputs: sr.ResearchInputs, day: pd.Timestamp, symbol: str = SYMBOL) -> list[pd.Timestamp]:
    """The bar calendar of the stock's own candles: the trading sessions after `day`, in order."""
    cal = sorted(set(_dates(inputs.raw[symbol])))
    return cal[cal.index(day) + 1 :]


def _rows(m: pd.DataFrame) -> pd.DataFrame:
    return m.set_index("decision_date")[COLS]


def _same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    return (
        list(a.index) == list(b.index) and a.to_numpy("float64").tobytes() == b.to_numpy("float64").tobytes()
    )


def _n_changed(a: pd.Series, b: pd.Series) -> int:
    return sum(np.float64(a[c]).tobytes() != np.float64(b[c]).tobytes() for c in COLS)


def run_battery(inputs: sr.ResearchInputs, day: str, h: int, sessions=SESSIONS) -> dict:
    """All checks for one decision day and one horizon. Returns a plain dict of facts (asserted by the tests)."""
    d = pd.Timestamp(day)
    spec = _spec(h)
    base = _rows(sr.assemble_training_matrix(spec, inputs))
    after_d = sessions_after(inputs, d)
    res: dict = {"day": day, "horizon": h, "base_rows": len(base), "in_base": d in base.index}

    # A. scramble everything dated after D
    mut = _rows(sr.assemble_training_matrix(spec, scramble_after(inputs, d)))
    upto = base.index <= d
    res["A_rows_up_to_D"] = int(upto.sum())
    res["A_identical_up_to_D"] = _same(base[upto], mut[mut.index <= d])
    res["A_row_D_identical"] = d in mut.index and _same(base.loc[[d]], mut.loc[[d]])
    res["A_later"] = {}
    for n in sessions:
        s = after_d[n - 1]
        both = s in base.index and s in mut.index
        res["A_later"][n] = {
            "date": s.date().isoformat(),
            "changed_inputs": _n_changed(base.loc[s], mut.loc[s]) if both else None,
        }

    # B. cut at the n-th next session
    res["B"] = {}
    for n in sessions:
        cut, nxt = after_d[n - 1], after_d[n]
        mb = _rows(sr.assemble_training_matrix(spec, scramble_after(inputs, cut)))
        k = base.index <= cut
        both = nxt in base.index and nxt in mb.index
        res["B"][n] = {
            "cut": cut.date().isoformat(),
            "rows_compared": int(k.sum()),
            "identical": _same(base[k], mb[mb.index <= cut]),
            "D_identical": d in mb.index and _same(base.loc[[d]], mb.loc[[d]]),
            "next_session": nxt.date().isoformat(),
            "next_changed_inputs": _n_changed(base.loc[nxt], mb.loc[nxt]) if both else None,
        }

    # C. mirror: the as-of builder at D equals the batch row at D
    exp = base.loc[[d]].to_numpy("float64").tobytes()
    variants = {
        "full": inputs,
        "truncated_after_D": truncate_after(inputs, d),
        "scrambled_after_D": scramble_after(inputs, d),
    }
    res["C"] = {}
    for name, inp in variants.items():
        row = sr.assemble_asof_row(inp, SYMBOL, d)
        res["C"][name] = row is not None and row[COLS].to_numpy("float64").tobytes() == exp
    return res


def _assert_battery(r: dict) -> None:
    assert r["in_base"], r
    assert r["A_identical_up_to_D"] and r["A_row_D_identical"], r
    for n, v in r["A_later"].items():  # power: the scramble reaches the row n sessions later
        assert v["changed_inputs"], (n, v)
    for n, v in r["B"].items():
        assert v["identical"] and v["D_identical"], (n, v)
        assert v["next_changed_inputs"], (n, v)  # power: the first row after the cut moved
    assert all(r["C"].values()), r["C"]


# ---------------------------------------------------------------------------------------------- fixtures
def _load_real_or_skip() -> sr.ResearchInputs:
    from swing_trade_ml.ml.sector_features_loader import connect_readonly

    try:
        connect_readonly(timeout=5).close()
    except Exception as e:  # noqa: BLE001  (unreachable DB: skip, never hang)
        pytest.skip(f"local Postgres unreachable: {type(e).__name__}")
    inputs = sr.load_inputs_readonly([SYMBOL])
    if SYMBOL not in inputs.raw or len(inputs.raw[SYMBOL]) < 400:
        pytest.skip("APOLLOHOSP candles not in the local database")
    return inputs


@pytest.fixture(scope="module")
def real_inputs():
    return _load_real_or_skip()


def _synthetic_inputs(n: int = 900, seed: int = 11) -> sr.ResearchInputs:
    rng = np.random.default_rng(seed)
    ts = (
        pd.DatetimeIndex(pd.bdate_range("2019-01-01", periods=n))
        .tz_localize("Asia/Kolkata")
        .tz_convert("UTC")
    )

    def ohlcv(start: float, vol: float = 1e6) -> pd.DataFrame:
        c = start * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n)))
        o = c * (1 + rng.normal(0, 0.003, n))
        return pd.DataFrame(
            {
                "ts": ts,
                "open": o,
                "high": np.maximum(o, c) * 1.004,
                "low": np.minimum(o, c) * 0.996,
                "close": c,
                "volume": rng.uniform(0.5, 1.5, n) * vol,
            }
        )

    frames = {u: ohlcv(1000.0 + 50 * i) for i, u in enumerate(sf.DEFAULT_RANK_UNIVERSE)}
    breadth = pd.DataFrame(
        {
            "ts": ts,
            "breadth_pct_above_sma50": rng.uniform(0.2, 0.8, n),
            "breadth_advance_pct": rng.uniform(0.2, 0.8, n),
        }
    )
    return sr.ResearchInputs(
        raw={SYMBOL: ohlcv(500.0)},
        index_df=ohlcv(15000.0, 0.0),
        index_frames=frames,
        vix_df=ohlcv(15.0, 0.0),
        breadth_df=breadth,
        source="synthetic",
    )


@pytest.fixture(scope="module")
def synthetic_inputs():
    return _synthetic_inputs()


# ---------------------------------------------------------------------------------------------- tests
_CACHE: dict = {}


def _cached(inputs, day, h):
    key = (id(inputs), day, h)
    if key not in _CACHE:
        _CACHE[key] = run_battery(inputs, day, h)
    return _CACHE[key]


@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("day", DECISION_DAYS)
def test_real_apollohosp_future_data_mutation(real_inputs, day, horizon):
    _assert_battery(_cached(real_inputs, day, horizon))


@pytest.mark.parametrize("horizon", HORIZONS)
def test_synthetic_future_data_mutation(synthetic_inputs, horizon):
    cal = sorted(set(_dates(synthetic_inputs.raw[SYMBOL])))
    for day in (cal[500], cal[501], cal[540]):
        _assert_battery(run_battery(synthetic_inputs, day.date().isoformat(), horizon))


def test_the_check_has_power_data_before_the_day_does_move_the_row(synthetic_inputs):
    """Sanity of the test itself: scrambling data dated BEFORE the decision day must move the row."""
    cal = sorted(set(_dates(synthetic_inputs.raw[SYMBOL])))
    d = cal[500]
    base = _rows(sr.assemble_training_matrix(_spec(5), synthetic_inputs))
    mut = _rows(sr.assemble_training_matrix(_spec(5), scramble_after(synthetic_inputs, cal[400])))
    assert not _same(base.loc[[d]], mut.loc[[d]])


def test_mutation_helper_touches_only_later_dates(synthetic_inputs):
    cal = sorted(set(_dates(synthetic_inputs.raw[SYMBOL])))
    d = cal[300]
    m = scramble_after(synthetic_inputs, d)
    for a, b in [
        (synthetic_inputs.raw[SYMBOL], m.raw[SYMBOL]),
        (synthetic_inputs.vix_df, m.vix_df),
        (synthetic_inputs.breadth_df, m.breadth_df),
    ]:
        old = (_dates(a) <= d).to_numpy()
        assert a[old].equals(b[old])
        assert not a[~old].reset_index(drop=True).equals(b[~old].reset_index(drop=True))
    assert len(sessions_after(synthetic_inputs, d)) == len(cal) - 301


# ---------------------------------------------------------------------------------------------- evidence writer
def results_markdown(inputs: sr.ResearchInputs) -> str:
    out = []
    for h in HORIZONS:
        out.append(f"\n### Horizon {h} ({'SX5' if h == 5 else 'SX10'})\n")
        out.append("| D | Check | n sessions after D | Date compared | Result |\n|---|---|---|---|---|")
        for day in DECISION_DAYS:
            r = run_battery(inputs, day, h)
            ok = r["A_identical_up_to_D"] and r["A_row_D_identical"]
            out.append(
                f"| {day} | A: scramble all data dated after D; row D and all {r['A_rows_up_to_D']} rows up to D "
                f"identical | - | {day} | {'PASS' if ok else 'FAIL'} |"
            )
            for n, v in r["A_later"].items():
                res = (
                    f"PASS ({v['changed_inputs']} of 56 inputs changed)"
                    if v["changed_inputs"]
                    else "NO CHANGE"
                )
                out.append(f"| {day} | A power: row n sessions later moves | {n} | {v['date']} | {res} |")
            for n, v in r["B"].items():
                ok = v["identical"] and v["D_identical"]
                out.append(
                    f"| {day} | B: cut at D+n, scramble after it; {v['rows_compared']} rows up to the cut identical "
                    f"| {n} | {v['cut']} | {'PASS' if ok else 'FAIL'}; next row {v['next_session']} changed in "
                    f"{v['next_changed_inputs']} of 56 inputs |"
                )
            for name, ok in r["C"].items():
                out.append(
                    f"| {day} | C mirror: as-of row == batch row, data {name} | - | {day} | {'PASS' if ok else 'FAIL'} |"
                )
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--write-md":
        Path(sys.argv[2]).write_text(results_markdown(sr.load_inputs_readonly([SYMBOL])), "utf-8")
    else:
        print(__doc__)
