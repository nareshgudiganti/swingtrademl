"""Availability + point-in-time audit of the 53 existing inputs, and their overlap with the four sector inputs.

READ-ONLY: SELECT on the local database, trains nothing, edits nothing in ml/features.py.

  python scripts/feature_availability_report.py --out-dir ../docs/brain/evidence/sector_prep

Writes `feature_audit_53.json`. Universe: the 49 model stocks (stock_split_ev15.json used_49) and the 47 that have an
official sector index.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from swing_trade_ml.ml import feature_audit as fa
from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_research as sr

REPO = Path(__file__).resolve().parents[2]
EVID = REPO / "docs/brain/evidence/sector_prep"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cutoff", default="2026-12-31")
    ap.add_argument("--pit-cuts", type=int, default=24, help="cut days per stock for the point-in-time check")
    a = ap.parse_args()
    used = list(
        json.loads((REPO / "docs/brain/evidence/stock_split/stock_split_ev15.json").read_text("utf-8"))[
            "used_49"
        ]
    )
    mapped = [s for s in used if sf.resolve_sector_index(s) is not None]
    inputs = sr.load_inputs_readonly(used)
    out: dict = {
        "stocks_49": len(used),
        "stocks_47": len(mapped),
        "unmapped": sorted(set(used) - set(mapped)),
    }

    for label, syms in (("mapped_47", mapped), ("all_49", used)):
        tab, per_stock = fa.availability(inputs, syms)
        out[f"availability_{label}"] = tab.to_dict("records")
        if label == "mapped_47":
            out["first_valid_by_stock_47"] = per_stock.to_dict("index")

    pit: dict[str, dict] = {}
    for sym in used:
        d = sr._ist_date(inputs.raw[sym]["ts"])
        step = max(1, (len(d) - 300) // a.pit_cuts)
        pit[sym] = fa.pit_check(inputs, sym, list(d.iloc[300 : len(d) - 1 : step]))
    agg: dict[str, dict] = {}
    for sym, res in pit.items():
        for c, v in res.items():
            g = agg.setdefault(
                c, {"checked": 0, "mismatches": 0, "stocks_with_mismatch": [], "max_abs_diff": 0.0}
            )
            g["checked"] += v["checked"]
            g["mismatches"] += v["mismatches"]
            g["max_abs_diff"] = max(g["max_abs_diff"], v["max_abs_diff"])
            if v["mismatches"]:
                g["stocks_with_mismatch"].append(f"{sym}:{v['example']}")
    out["pit_cut_vs_full"] = agg
    mut = {}
    for sym in used[:12]:
        d = sr._ist_date(inputs.raw[sym]["ts"])
        mut[sym] = {c: n for c, n in fa.mutation_check(inputs, sym, d.iloc[len(d) // 2]).items() if n}
    out["mutation_after_T_changed_inputs_on_or_before_T"] = mut

    ex = EVID / "excluded_rows_h5_v2.csv"
    spec = sr.DatasetSpec(
        candidate="SX5",
        symbols=tuple(mapped),
        horizon_days=5,
        target_return=0.02,
        stop_return=None,
        label_kind="endpoint",
        data_cutoff=date.fromisoformat(a.cutoff),
        exclusions=sr.load_exclusions_csv(ex) if ex.is_file() else frozenset(),
    )
    m = sr.assemble_training_matrix(spec, inputs)
    out["matrix_rows_sx5_47"] = int(len(m))
    out["matrix_rows_sha256_canonical"] = __import__(
        "swing_trade_ml.ml.sector_walkforward", fromlist=["x"]
    ).rows_sha256(m)
    out["overlap"] = fa.overlap(m)
    Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    (Path(a.out_dir) / "feature_audit_53.json").write_text(
        json.dumps(out, indent=1, sort_keys=True, default=str), "utf-8"
    )
    bad = {c: v for c, v in agg.items() if v["mismatches"]}
    print("stocks", len(used), len(mapped), "| matrix rows", len(m), "| PIT failing inputs:", sorted(bad))


if __name__ == "__main__":
    main()
