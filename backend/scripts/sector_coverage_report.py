"""Coverage of the sector-only candidates (SX5 / SX10) on the local data. READ-ONLY (SELECT), writes one JSON.

For each stock and decision day: does a BASELINE row exist (all existing FEATURE_COLUMNS and, for the label
view, a known label) and does a CHALLENGER row exist (also the three research sector inputs)? Counts the rows removed
specifically because the sector inputs are missing, split by cause, overall and by sector index.

  python scripts/sector_coverage_report.py --out ../docs/brain/evidence/sector_prep/sector_coverage_sx.json

Nothing is trained, written to the database or wired anywhere.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_research as sr

REPO = Path(__file__).resolve().parents[2]
MIN_HISTORY = 252
CAUSES = (
    "unmapped_stock",
    "calendar_warmup_20",
    "late_start_index",
    "rank_invalid_only",
    "other_gap_or_stale",
)


def _groups():
    split = json.loads(
        (REPO / "docs/brain/evidence/stock_split/stock_split_ev15.json").read_text(encoding="utf-8")
    )
    lane = json.loads(
        (REPO / "docs/brain/evidence/lane_universe/lane_universe_v1.json").read_text(encoding="utf-8")
    )
    return {"large_49": list(split["used_49"]), "mid_14": list(lane["mid"])}


def _per_stock(sym, inputs, nifty, secs, horizon, excl):
    """Returns a DataFrame indexed by session with bool columns for the views, and a cause label."""
    raw = inputs.raw[sym].sort_values("ts").reset_index(drop=True)
    from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_label

    feat = sr._existing_features(raw, inputs, sym)
    base_ok = ~feat[FEATURE_COLUMNS].isna().any(axis=1)  # feature-only view
    lab = build_label(feat, horizon, 0.02, 0.02)  # label NaN-ness only; the rule does not change coverage
    has_label = pd.Series(False, index=feat.index)
    has_label.loc[lab.index] = True
    date = sr._ist_date(raw["ts"])
    idx_name = sf.resolve_sector_index(sym)
    stock_close = sf.close_series_from_candles(raw[["ts", "close"]])
    sec = sf.build_sector_features(stock_close, nifty, secs, idx_name)
    sec_ok = (
        pd.Series(sec[list(sr.SECTOR_COLUMNS)].notna().all(axis=1).reindex(date).to_numpy(), index=feat.index)
        .fillna(False)
        .astype(bool)
    )

    # cause for rows whose sector inputs are missing
    cal = sec.index
    pos_in_cal = pd.Series(cal.get_indexer(date), index=feat.index)
    cause = pd.Series("", index=feat.index, dtype=object)
    if idx_name is None:
        cause[:] = "unmapped_stock"
    else:
        first_idx = secs[idx_name].index.min()
        sec_aligned = sec.reindex(date.to_numpy())
        sec_aligned.index = feat.index
        for i in feat.index[~sec_ok]:
            p = pos_in_cal[i]
            if p < 0:
                cause[i] = "other_gap_or_stale"  # the stock has a bar on a day no index traded
            elif p < sf.LONG_WINDOW:
                cause[i] = "calendar_warmup_20"
            elif first_idx > cal[p - sf.LONG_WINDOW]:
                cause[i] = "late_start_index"
            else:
                r = sec_aligned.loc[i]
                others_ok = r[[c for c in sr.SECTOR_COLUMNS if c != sf.SECTOR_RANK_10D]].notna().all()
                cause[i] = (
                    "rank_invalid_only"
                    if (others_ok and np.isnan(r[sf.SECTOR_RANK_10D]))
                    else "other_gap_or_stale"
                )
    pos = pd.Series(np.arange(len(feat)), index=feat.index)
    keep = pd.Series([(sym, d.strftime("%Y-%m-%d")) not in excl for d in date], index=feat.index)
    return pd.DataFrame(
        {
            "date": date,
            "pos": pos,
            "base_feat": base_ok,
            "has_label": has_label,
            "sec_ok": sec_ok,
            "cause": cause,
            "not_excluded": keep,
            "index": idx_name or "NO SECTOR",
        }
    )


def _daily_stats(per_day: pd.Series, all_days: pd.DatetimeIndex) -> dict:
    s = per_day.reindex(all_days).fillna(0).astype(int)
    return {
        "days": int(len(s)),
        "min": int(s.min()),
        "median": float(s.median()),
        "max": int(s.max()),
        "days_below_20": int((s < 20).sum()),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--excl-suffix", default="", help="e.g. _v2: reads excluded_rows_h{5,10}{suffix}.csv")
    a = ap.parse_args(argv)
    groups = _groups()
    allsyms = sorted({s for g in groups.values() for s in g})
    inputs = sr.load_inputs_readonly(allsyms)
    nifty, secs = sr._closes(inputs)
    out: dict = {"groups": {k: len(v) for k, v in groups.items()}, "views": {}}
    excl = {
        5: sr.load_exclusions_csv(
            REPO / f"docs/brain/evidence/sector_prep/excluded_rows_h5{a.excl_suffix}.csv"
        ),
        10: sr.load_exclusions_csv(
            REPO / f"docs/brain/evidence/sector_prep/excluded_rows_h10{a.excl_suffix}.csv"
        ),
    }
    for horizon in (5, 10):
        stocks = {
            s: _per_stock(s, inputs, nifty, secs, horizon, excl[horizon])
            for s in allsyms
            if len(inputs.raw[s])
        }
        for gname, members in groups.items():
            members = [m for m in members if m in stocks]
            res = {}
            for view in (
                "rows_protocol",
                "rows_protocol_with_exclusions",
                "rows_no_warmup_skip",
                "stockdays_protocol",
            ):
                base_sets, chal_sets = {}, {}
                removed = Counter()
                removed_by_idx: dict = defaultdict(Counter)
                base_by_idx = Counter()
                for s in members:
                    d = stocks[s]
                    if view == "stockdays_protocol":
                        base = d["base_feat"] & (d["pos"] >= MIN_HISTORY)
                    elif view == "rows_no_warmup_skip":
                        base = d["base_feat"] & d["has_label"]
                    else:
                        base = d["base_feat"] & d["has_label"] & (d["pos"] >= MIN_HISTORY)
                        if view == "rows_protocol_with_exclusions":
                            base = base & d["not_excluded"]
                    chal = base & d["sec_ok"]
                    base_sets[s] = d.loc[base, "date"]
                    chal_sets[s] = d.loc[chal, "date"]
                    base_by_idx[d["index"].iloc[0]] += int(base.sum())
                    for c, n in d.loc[base & ~d["sec_ok"], "cause"].value_counts().items():
                        removed[c] += int(n)
                        removed_by_idx[d["index"].iloc[0]][c] += int(n)
                bcount = pd.concat(base_sets.values()).value_counts().sort_index()
                ccount = pd.concat(chal_sets.values()).value_counts().sort_index()
                days = bcount.index  # days with at least one baseline-eligible stock
                nb, nrm = int(sum(len(v) for v in base_sets.values())), int(sum(removed.values()))
                res[view] = {
                    "baseline_rows": nb,
                    "challenger_rows": nb - nrm,
                    "removed_because_sector_missing": nrm,
                    "removed_pct_of_baseline": round(100.0 * nrm / max(nb, 1), 3),
                    "removed_by_cause": {c: removed.get(c, 0) for c in CAUSES},
                    "removed_by_cause_pct_of_baseline": {
                        c: round(100.0 * removed.get(c, 0) / max(nb, 1), 3) for c in CAUSES
                    },
                    "baseline_eligible_per_day": _daily_stats(bcount, days),
                    "challenger_eligible_per_day": _daily_stats(ccount, days),
                    "by_sector": {
                        k: {
                            "baseline_rows": base_by_idx[k],
                            "removed": int(sum(removed_by_idx[k].values())),
                            "removed_pct": round(
                                100.0 * sum(removed_by_idx[k].values()) / max(base_by_idx[k], 1), 3
                            ),
                            "by_cause": dict(removed_by_idx[k]),
                        }
                        for k in sorted(base_by_idx)
                    },
                }
            # the structural 252-session warm-up (NOT caused by sector inputs): rows lost between views
            a_rows = sum(int((stocks[s]["base_feat"] & stocks[s]["has_label"]).sum()) for s in members)
            b_rows = res["rows_protocol"]["baseline_rows"]
            res["structural_warmup_252_rows"] = {
                "baseline_rows_without_skip": a_rows,
                "baseline_rows_after_skip": b_rows,
                "rows_lost_to_252_skip": a_rows - b_rows,
                "pct_of_without_skip": round(100.0 * (a_rows - b_rows) / max(a_rows, 1), 3),
            }
            out["views"][f"h{horizon}_{gname}"] = res
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                k: {kk: vv for kk, vv in v.items() if kk != "rows_no_warmup_skip"}
                for k, v in out["views"].items()
            },
            indent=1,
        )[:12000]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
