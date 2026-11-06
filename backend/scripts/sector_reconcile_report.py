"""Row reconciliation report for SX5 / SX10 (READ-ONLY: SELECT on the local database; trains nothing).

  python scripts/sector_reconcile_report.py --events <events.csv> --out-dir ../docs/brain/evidence/sector_prep

Writes `reconciliation_v2.json`, `reconciliation_v2.md` and the canonical eligible row lists (`*_rows_v2.txt.gz`).
Universes: (i) the SX universe = the 49 model stocks that have an official sector index (47), sector inputs required;
(ii) the full 49 with the existing inputs only (separate baseline); (iii) the MATCHED baseline = existing inputs on
exactly the rows of (i).
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from swing_trade_ml.ml import exclusion_report as er
from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_reconcile as rc
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_label

REPO = Path(__file__).resolve().parents[2]
MIN_HISTORY = 252


def _universe():
    split = json.loads(
        (REPO / "docs/brain/evidence/stock_split/stock_split_ev15.json").read_text(encoding="utf-8")
    )
    used = list(split["used_49"])
    mapped = [s for s in used if sf.resolve_sector_index(s) is not None]
    return used, mapped


def _stock_arrays(sym, inputs, nifty, secs, horizon):
    raw = inputs.raw[sym].sort_values("ts").reset_index(drop=True)
    feat = sr._existing_features(raw, inputs, sym)
    base_ok = ~feat[FEATURE_COLUMNS].isna().any(axis=1)
    lab = build_label(feat, horizon, 0.02, 0.02)
    has_label = pd.Series(False, index=feat.index)
    has_label.loc[lab.index] = True
    feat_ok = (base_ok & has_label).to_numpy()
    d = sr._ist_date(raw["ts"])
    dates = [x.date() for x in d]
    idx_name = sf.resolve_sector_index(sym)
    sec = sf.build_sector_features(sf.close_series_from_candles(raw[["ts", "close"]]), nifty, secs, idx_name)
    sec_ok = (
        pd.Series(sec[list(sr.SECTOR_COLUMNS)].notna().all(axis=1).reindex(d).to_numpy())
        .fillna(False)
        .to_numpy(dtype=bool)
    )
    nan_cols = feat[FEATURE_COLUMNS].isna().sum().to_dict()
    return dates, feat_ok, sec_ok, {k: int(v) for k, v in nan_cols.items() if v}


def _table(per, hits_by, required_sector, horizon):
    tot: dict[str, int] = {}
    overlap: dict[str, int] = {}
    events: dict[str, dict] = {}
    ev_overlap: dict[str, int] = {}
    keys: list[str] = []
    per_stock = {}
    for sym, (dates, feat_ok, sec_ok) in per.items():
        r = rc.reconcile_stock(
            dates,
            hits_by.get(sym, []),
            feat_ok,
            sec_ok if required_sector else None,
            horizon=horizon,
            min_history=MIN_HISTORY,
        )
        rc.add_counts(tot, r.counts)
        for (a, b), v in r.overlap.items():
            overlap[f"{a}+{b}"] = overlap.get(f"{a}+{b}", 0) + v
        for e, v in r.event_rows.items():
            events[e] = {"rows": v, "by_window": dict(r.event_kind.get(e, {}))}
        for (a, b), v in r.event_overlap.items():
            ev_overlap[f"{a}+{b}"] = ev_overlap.get(f"{a}+{b}", 0) + v
        k = r.final_keys(sym)
        keys += k
        per_stock[sym] = {**r.counts}
    return (
        {
            "counts": tot,
            "overlap": overlap,
            "events": events,
            "event_overlap": ev_overlap,
            "final_rows": len(keys),
            "sha256": rc.keys_sha256(keys),
        },
        keys,
        per_stock,
    )


def _row(label, c):
    return (
        f"| {label} | {c['raw']} | {c['warm_up']} | {c['label_incomplete']} | {c['event']} | {c['existing_gap']} "
        f"| {c['sector_gap']} | **{c['final']}** |"
    )


def render_md(res: dict) -> str:
    L = [
        "# Row reconciliation v2: SX5 / SX10 eligible rows (PREPARATION; nothing trained)",
        "",
        "Each raw stock-day row is counted ONCE, against the first reason that applies, in this order: "
        "warm-up (first 252 sessions) -> label incomplete (last h sessions) -> corporate-action event window "
        "-> existing-input gap -> sector gap. Rows that also meet a later reason are in the overlap tables.",
        f"Universe: {res['universe']['used_49']} model stocks; SX universe = {res['universe']['sx_mapped']} mapped; "
        f"unmapped (features missing, never 0): {', '.join(res['universe']['unmapped'])}.",
        f"Events file rows: {res['events_file_rows']}. Adjustment status: RELIANCE 2023-07-20 and ITC 2025-01-06 "
        "ADJUSTED_OK (retained, flagged); HINDUNILVR 2025-12-05 PENDING (removed); BAJAJELEC 2023-09-14 PENDING "
        "(not in the 49).",
        "",
    ]
    for h in ("h5", "h10"):
        x = res["horizons"][h]
        L += [
            f"## Horizon {h[1:]} sessions",
            "",
            "| universe | raw rows | warm-up | label incomplete | event windows | existing-input gap | sector gap | final eligible |",
            "|---|---|---|---|---|---|---|---|",
            _row("(i) SX 47 mapped, sector required", x["sx_47"]["counts"]),
            _row("(ii) full 49 baseline, existing inputs only", x["full_49_baseline"]["counts"]),
            "",
            f"(iii) Matched baseline = existing inputs on exactly the (i) rows: **{x['matched_baseline']['final_rows']}** rows "
            f"(a subset of (ii): {x['matched_baseline']['subset_of_full_49_baseline']}).",
            "",
            "| set | final rows | dataset sha256 (sorted SYMBOL and DATE) |",
            "|---|---|---|",
            f"| (i) SX 47 | {x['sx_47']['final_rows']} | `{x['sx_47']['sha256']}` |",
            f"| (ii) full 49 baseline | {x['full_49_baseline']['final_rows']} | `{x['full_49_baseline']['sha256']}` |",
            f"| (iii) matched baseline | {x['matched_baseline']['final_rows']} | `{x['matched_baseline']['sha256']}` (same row list as (i)) |",
            "",
            "Exclusion-report policy numbers (event rows only, before the existing-input gap stage): "
            f"buildable {x['exclusion_report_policy_counts']['buildable_rows']}, excluded "
            f"{x['exclusion_report_policy_counts']['excluded_unique_rows']} "
            f"{x['exclusion_report_policy_counts']['excluded_by_window_type_row_counts']}, retained "
            f"{x['exclusion_report_policy_counts']['retained_rows']}, sha256 "
            f"`{x['exclusion_report_policy_counts']['dataset_sha256']}`.",
            "",
            "### Events (each row once; earliest event wins)",
            *(f"- (i) {k}: {v['rows']} rows {v['by_window']}" for k, v in x["sx_47"]["events"].items()),
            f"- event vs event overlap: {x['sx_47']['event_overlap'] or 'none'}",
            "",
            "### Overlaps: rows counted at the first stage that also meet a later reason",
            "| universe | overlap | rows |",
            "|---|---|---|",
            *(f"| (i) SX 47 | {k} | {v} |" for k, v in x["sx_47"]["overlap"].items()),
            *(f"| (ii) full 49 | {k} | {v} |" for k, v in x["full_49_baseline"]["overlap"].items()),
            "",
            "Event windows that also have a sector gap: "
            f"{x['sx_47']['overlap'].get('event+sector_gap', 0)} rows (HINDUNILVR window vs sector gaps).",
            "",
            "### Coverage loss of the SX 47 versus the full-49 baseline",
            f"{x['sx_loss_vs_full_49']['rows']} rows ({x['sx_loss_vs_full_49']['pct']}% of the full-49 baseline): "
            f"{x['sx_loss_vs_full_49']['by_stock']}. ASIANPAINT and BHARTIARTL are unmapped; APOLLOHOSP loses rows "
            "because NIFTY HEALTHCARE history is incomplete early.",
            "",
            "### Cross-check against the research assembler (`assemble_training_matrix`)",
            f"{x['assembler_cross_check']}",
            "",
        ]
    return chr(10).join(L) + chr(10)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cutoff", default="2026-12-31", help="matrix cross-check data cut-off (IST date)")
    ap.add_argument(
        "--suffix", default="_v2", help="file-name suffix of the outputs (use _v3 for the 3-input challenger)"
    )
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    used, mapped = _universe()
    events = er.load_events(a.events)
    inputs = sr.load_inputs_readonly(used)
    nifty, secs = sr._closes(inputs)
    result: dict = {
        "universe": {
            "used_49": len(used),
            "sx_mapped": len(mapped),
            "unmapped": sorted(set(used) - set(mapped)),
        },
        "order_of_reasons": list(rc.STAGES),
        "events_file_rows": len(events),
        "horizons": {},
    }
    for h in (5, 10):
        per, nan_cols = {}, {}
        for s in used:
            dates, feat_ok, sec_ok, nc = _stock_arrays(s, inputs, nifty, secs, h)
            per[s] = (dates, feat_ok, sec_ok)
            for c, v in nc.items():
                nan_cols[c] = nan_cols.get(c, 0) + v
        dates_by = {s: v[0] for s, v in per.items()}
        pol = er.Policy(horizon=h)
        hits = er.excluded_rows(dates_by, events, pol)
        hits_by: dict[str, list] = {}
        for x in hits:
            hits_by.setdefault(x["symbol"], []).append(x)
        report_summary = er.summarise(dates_by, events, pol)
        sx, sx_keys, sx_stock = _table({s: per[s] for s in mapped}, hits_by, True, h)
        full, full_keys, full_stock = _table(per, hits_by, False, h)
        full_with_sector, _, _ = _table(per, hits_by, True, h)
        matched_keys = list(sx_keys)
        # coverage loss of the SX universe against the full-49 baseline
        lost = sorted(set(full_keys) - set(sx_keys))
        lost_by = {}
        for k in lost:
            sym = k.split("|")[0]
            lost_by[sym] = lost_by.get(sym, 0) + 1
        # cross-check: the research assembler must produce exactly the SX rows
        spec = sr.DatasetSpec(
            candidate=f"SX{h}",
            symbols=tuple(mapped),
            horizon_days=h,
            target_return=0.02,
            stop_return=0.02,
            data_cutoff=date.fromisoformat(a.cutoff),
            exclusions=sr.exclusions_from_hits(hits),
        )
        m = sr.assemble_training_matrix(spec, inputs)
        mk = set((m["symbol"] + "|" + m["decision_date"].dt.strftime("%Y-%m-%d")).tolist())
        result["horizons"][f"h{h}"] = {
            "exclusion_report_policy_counts": {k: v for k, v in report_summary.items() if k not in ("hits",)},
            "sx_47": sx,
            "full_49_baseline": full,
            "full_49_if_sector_required_info": {
                k: full_with_sector[k] for k in ("counts", "final_rows", "sha256")
            },
            "matched_baseline": {
                "definition": "existing inputs, exactly the SX 47 eligible rows",
                "final_rows": len(matched_keys),
                "sha256": rc.keys_sha256(matched_keys),
                "subset_of_full_49_baseline": rc.is_subset(matched_keys, full_keys),
            },
            "sx_loss_vs_full_49": {
                "rows": len(lost),
                "by_stock": lost_by,
                "pct": round(100 * len(lost) / len(full_keys), 3),
            },
            "assembler_cross_check": {
                "assembler_rows": len(mk),
                "reconciliation_rows": len(sx_keys),
                "identical_row_sets": mk == set(sx_keys),
                "only_in_assembler": len(mk - set(sx_keys)),
                "only_in_reconciliation": len(set(sx_keys) - mk),
            },
            "existing_input_missing_counts_all_rows_by_column": dict(
                sorted(nan_cols.items(), key=lambda kv: -kv[1])
            ),
            "per_stock_sx": sx_stock,
            "per_stock_full": full_stock,
        }
        for nm, ks in ((f"sx{h}_47", sx_keys), (f"full49_h{h}", full_keys)):
            with gzip.open(out / f"{nm}_rows{a.suffix}.txt.gz", "wt", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(sorted(ks)) + "\n")
    (out / f"reconciliation{a.suffix}.json").write_text(
        json.dumps(result, indent=1, default=str), encoding="utf-8"
    )
    (out / f"reconciliation{a.suffix}.md").write_text(render_md(result), encoding="utf-8")
    print(
        json.dumps(
            {
                h: {
                    k: v
                    for k, v in d.items()
                    if k
                    in (
                        "sx_47",
                        "full_49_baseline",
                        "matched_baseline",
                        "sx_loss_vs_full_49",
                        "assembler_cross_check",
                    )
                }
                for h, d in result["horizons"].items()
            },
            indent=1,
            default=str,
        )[:9000]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
