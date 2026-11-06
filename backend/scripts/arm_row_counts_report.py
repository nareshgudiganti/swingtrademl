"""Row counts per fold and per arm (A_53, R_37, C_56) for SX5 and SX10. READ-ONLY (SELECT); fits NO model.

  python scripts/arm_row_counts_report.py --out-dir ../docs/brain/evidence/sector_prep --suffix _v3

Writes `arm_row_counts{suffix}.json` and `sx{5,10}_fold_coverage{suffix}.csv`. Also records the arm labels, the sha256 of
each arm's feature manifest, and the `config_sha256` of the SX5 / SX10 DatasetSpec (symbols = the 47 mapped stocks,
exclusions = excluded_rows_h{5,10}_v2.csv, data cut-off 2026-12-31 as in every earlier evidence file) next to what the same
spec hashed to with the former 57-column challenger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml import sector_walkforward as wf

REPO = Path(__file__).resolve().parents[2]
EVID = REPO / "docs/brain/evidence/sector_prep"
CUTOFF = date(2026, 12, 31)
FORMER_COLUMNS = [*sr.FEATURE_COLUMNS, *sf.FEATURE_NAMES]  # the 57 columns of the former C_57


def _spec(candidate: str, symbols) -> sr.DatasetSpec:
    h = sr.CANDIDATE_HORIZON[candidate]
    kind, target, stop = sr.PROTOCOL_LABELS[candidate]
    ex = EVID / f"excluded_rows_h{h}_v2.csv"
    return sr.DatasetSpec(
        candidate=candidate,
        symbols=tuple(symbols),
        horizon_days=h,
        target_return=target,
        stop_return=stop,
        label_kind=kind,
        data_cutoff=CUTOFF,
        exclusions=sr.load_exclusions_csv(ex),
    )


def _sha_of_config(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--suffix", default="_v3")
    a = ap.parse_args()
    out_dir = Path(a.out_dir)
    used = list(
        json.loads((REPO / "docs/brain/evidence/stock_split/stock_split_ev15.json").read_text("utf-8"))[
            "used_49"
        ]
    )
    mapped = [s for s in used if sf.resolve_sector_index(s) is not None]
    inputs = sr.load_inputs_readonly(used)
    arms = wf.build_arms()
    result: dict = {
        "schema": "arm_row_counts_v3",
        "arms": {
            k: {
                "label": wf.ARM_LABELS[k],
                "n_columns": len(v),
                "feature_list_sha256": wf.feature_list_sha256(v),
                "manifest_sha256": hashlib.sha256(json.dumps(list(v)).encode()).hexdigest(),
            }
            for k, v in arms.items()
        },
        "r37_known_semantic_differences": list(wf.R37_KNOWN_SEMANTIC_DIFFERENCES),
        "r37_other_notes": list(wf.R37_OTHER_NOTES),
    }
    for cand in ("SX5", "SX10"):
        spec = _spec(cand, mapped)
        m = sr.assemble_training_matrix(spec, inputs)
        h = spec.horizon_days
        plan = wf.plan_folds(m, wf.default_folds(include_holdout=True), embargo=h)
        missing = {k: int(m[list(c)].isna().sum().sum()) for k, c in arms.items()}
        cfg = spec.to_config()
        former = {**cfg, "columns": FORMER_COLUMNS}
        result[cand] = {
            "plan": plan,
            "rows": int(len(m)),
            "rows_sha256": wf.rows_sha256(m),
            "missing_values_by_arm": missing,
            "arms_have_identical_rows_in_every_fold": all(
                len({(x["rows_train"], x["rows_test"]) for x in p["arms"].values()}) == 1 for p in plan
            ),
            "config_sha256": spec.config_sha256(),
            "config_sha256_former_57_column_challenger": _sha_of_config(former),
            "config_sha256_prefix": spec.config_sha256()[:16],
            "config_sha256_former_prefix": _sha_of_config(former)[:16],
        }
        lines = ["fold,test_start,test_end,test_days,test_rows,train_rows_after_embargo"]
        for p in plan:
            if p["kind"] == "dev":
                lines.append(
                    f"{p['index'] + 1},{p['test_start']},{p['test_end']},{p['test_days']},{p['n_test']},{p['n_train']}"
                )
            else:  # counts only: the holdout is not scored here
                lines.append(f"holdout,{p['test_start']},{p['test_end']},{p['test_days']},{p['n_test']},")
        (out_dir / f"{cand.lower()}_fold_coverage{a.suffix}.csv").write_text("\n".join(lines) + "\n", "utf-8")
    (out_dir / f"arm_row_counts{a.suffix}.json").write_text(
        json.dumps(result, indent=1, sort_keys=True, default=str), "utf-8"
    )
    print(
        {
            c: (
                result[c]["rows"],
                result[c]["config_sha256_prefix"],
                result[c]["config_sha256_former_prefix"],
            )
            for c in ("SX5", "SX10")
        }
    )


if __name__ == "__main__":
    main()
