"""Do the model's scores come true? Claimed score vs how often the idea really hit +8% before -4%.

Reuses the walk-forward machinery: each fold trains a model that knows outcomes only up to its
cutoff, scores the unseen days after it, and every stock-day is scored with the strict rule.
Then, fold by fold, a calibration map (isotonic) is fitted ONLY on earlier folds whose picks had
finished by then, and applied to the next fold. Prints raw vs calibrated reliability and Brier.

Read-only evidence: registers trial models (wf_*, never activated), writes one report.
Run: backend/.venv/Scripts/python.exe docs/brain/evidence/score_reliability.py --from 2025-10-01
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sqlalchemy import select

from swing_trade_ml.brain.replay_score import load_bars
from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, STOP, TARGET
from swing_trade_ml.brain.walk_forward import (
    SETTLE_DAYS,
    _train,
    latest_scoreable_end,
    make_folds,
    outcomes_for,
)
from swing_trade_ml.core.market_session import last_closed_trading_day
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.session import SessionLocal
from swing_trade_ml.ml.asof import score_series

BANDS = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0001]


def collect(db, first_start: date, last_end: date, test_days: int) -> list[dict]:
    instruments = list(
        db.execute(
            select(Instrument).where(
                Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True)
            )
        ).scalars()
    )
    bars = {
        s: df
        for s, df in load_bars(
            db, [i.tradingsymbol for i in instruments], last_end + timedelta(days=60)
        ).items()
        if len(df)
    }
    rows: list[dict] = []
    for fold in make_folds(first_start, last_end, test_days):
        days = sorted(
            {
                d
                for df in bars.values()
                for d in df["day"]
                if fold.start <= d <= fold.end
            }
        )
        if not days:
            continue
        outcomes = outcomes_for(bars, days, HORIZON_BARS, TARGET, STOP)
        model = _train(db, fold.cutoff, HORIZON_BARS, TARGET, STOP)
        for inst in instruments:
            for d, p in score_series(db, inst, model, fold.cutoff).items():
                o = outcomes.get((inst.tradingsymbol, d))
                if (
                    fold.start <= d <= fold.end
                    and o is not None
                    and o.net_return is not None
                ):
                    rows.append(
                        {
                            "fold": fold.start.isoformat(),
                            "end": fold.end.isoformat(),
                            "day": d.isoformat(),
                            "p": float(p),
                            "hit": int(o.status == "target"),
                        }
                    )
        print("fold done", fold.start, len(rows), flush=True)
    return rows


def table(p: np.ndarray, y: np.ndarray) -> list[dict]:
    out = []
    for lo, hi in pairwise(BANDS):
        m = (p >= lo) & (p < hi)
        if m.any():
            out.append(
                {
                    "band": f"{lo:.0%}-{min(hi, 1):.0%}",
                    "n": int(m.sum()),
                    "claimed": float(p[m].mean()),
                    "really_hit": float(y[m].mean()),
                }
            )
    return out


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def analyse(rows: list[dict]) -> dict:
    folds = sorted({r["fold"] for r in rows})
    p = np.array([r["p"] for r in rows])
    y = np.array([r["hit"] for r in rows], dtype=float)
    cal_p, cal_y, base_p, used = [], [], [], []
    for f in folds:
        start = date.fromisoformat(f)
        # only folds whose every pick had finished before this fold starts
        past = [
            r
            for r in rows
            if date.fromisoformat(r["end"]) + timedelta(days=SETTLE_DAYS) < start
        ]
        if len(past) < 2000 or len({r["fold"] for r in past}) < 2:
            continue
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
            [r["p"] for r in past], [r["hit"] for r in past]
        )
        now = [r for r in rows if r["fold"] == f]
        cal_p += list(iso.predict([r["p"] for r in now]))
        cal_y += [r["hit"] for r in now]
        base_p += [float(np.mean([r["hit"] for r in past]))] * len(now)
        used.append(f)
    cal_p, cal_y, base_p = (
        np.array(cal_p),
        np.array(cal_y, dtype=float),
        np.array(base_p),
    )
    raw_sub = np.array([r["p"] for r in rows if r["fold"] in used])
    return {
        "stock_days": len(rows),
        "overall_hit_rate": float(y.mean()),
        "raw_table_all_folds": table(p, y),
        "folds_evaluated_with_calibration": used,
        "raw_table_same_folds": table(raw_sub, cal_y),
        "calibrated_table": table(cal_p, cal_y),
        "brier": {
            "raw": brier(raw_sub, cal_y),
            "calibrated": brier(cal_p, cal_y),
            "always_say_base_rate": brier(base_p, cal_y),
        },
        "top_score_calibrated_hit": float(
            cal_y[cal_p >= np.quantile(cal_p, 0.95)].mean()
        )
        if len(cal_p)
        else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--test-days", type=int, default=28)
    ap.add_argument(
        "--rows", default=None, help="reuse a saved rows json instead of retraining"
    )
    ap.add_argument("--out", default="docs/brain/evidence")
    ap.add_argument(
        "--write-evidence",
        action="store_true",
        help="also write the display evidence the idea cards read (brain/score_evidence_barrier.json)",
    )
    a = ap.parse_args()
    if a.rows:
        rows = json.loads(Path(a.rows).read_text())
    else:
        end = (
            date.fromisoformat(a.end)
            if a.end
            else latest_scoreable_end(last_closed_trading_day(datetime.now(UTC)))
        )
        with SessionLocal() as db:
            rows = collect(db, date.fromisoformat(a.start), end, a.test_days)
        Path(a.out, "score_reliability_rows.json").write_text(json.dumps(rows))
    res = analyse(rows)
    Path(a.out, "score_reliability.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    if a.write_evidence:
        from swing_trade_ml.brain import score_evidence

        ev = score_evidence.build(rows, datetime.now(UTC).date().isoformat())
        score_evidence.EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        score_evidence.EVIDENCE_FILE.write_text(
            json.dumps(ev, indent=1), encoding="utf-8"
        )
        print("evidence written:", score_evidence.EVIDENCE_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
