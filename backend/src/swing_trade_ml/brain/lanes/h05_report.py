# backend/src/swing_trade_ml/brain/lanes/h05_report.py
# ruff: noqa: E501, N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""Numbers for the h05 lane, per run and per size group. Never pooled across groups.

Before the owner accepts the protocol the report shows measurements and NO verdict. After acceptance the
frozen verdict (`h05_verdict`) is calculated mechanically, group by group, when a run is closed and every
outcome has matured. A score is a ranking number, never a probability of profit. Results are hypothetical
fixed-rule selections, not executable portfolio returns.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import fmean

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_rules as R
from swing_trade_ml.brain.lanes import h05_verdict as V
from swing_trade_ml.core.market_session import last_closed_trading_day
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run, H05Signal

NO_VERDICT = (
    "No verdict is calculated: the protocol has not been accepted. These are measurements. "
    "Three positive runs would not by themselves prove an edge."
)
SCORE_NOTE = "A score is a ranking number for this model. It is not a probability of profit."
RESOLVED = ("target", "stop", "expiry")
DIAGNOSTIC_NOTE = "DIAGNOSTIC: a breakdown of the same frozen result. It is not a second chance to pass."


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _by_day(rows: list[dict], key) -> dict:
    out: dict = defaultdict(list)
    for r in rows:
        v = key(r)
        if v is not None:
            out[r["signal_day"]].append(v)
    return out


def _daily_edge(picked: dict, pool: dict) -> list[float]:
    """Per signal day (in order): the picks' average minus the average of every eligible stock."""
    return [fmean(picked[d]) - fmean(pool[d]) for d in sorted(picked) if picked.get(d) and pool.get(d)]


def _range(edge: list[float]) -> dict:
    rule = P.RUN_VALUES["verdict_rule"]
    r = R.block_range(edge, block=rule["block_days"], level=rule["range_level"])
    return {
        "days": len(edge),
        "mean": _mean(edge),
        "low": r[0] if r else None,
        "high": r[1] if r else None,
        "level": rule["range_level"],
        "note": None if r else "too few signal days for a range",
    }


def _endpoint(sel: list[dict]) -> dict:
    hits = [r["label_hit"] for r in sel if r["label_status"] == "evaluated"]
    return {"n": len(hits), "hit_rate": (sum(hits) / len(hits)) if hits else None}


def _trade(sel: list[dict], net_key: str = "net_return", status_key: str = "trade_status") -> dict:
    done = [r for r in sel if r[status_key] in RESOLVED and r[net_key] is not None]
    nets = [r[net_key] for r in done]
    return {
        "finished": len(done),
        "mean_net_return": _mean(nets),
        "win_rate": (sum(1 for x in nets if x > 0) / len(nets)) if nets else None,
        "exits": dict(Counter(r[status_key] for r in done)),
        "unresolved": sum(1 for r in sel if r[status_key] == "unresolved"),
        "pending": sum(1 for r in sel if r[status_key] == "pending"),
        "ambiguous_same_candle": sum(1 for r in done if r["ambiguous"]),
        "gap_fills": sum(1 for r in done if r["gap_fill"]),
        "corporate_action_flagged": sum(
            1 for r in done if "possible_corporate_action" in (r["trade_flags"] or [])
        ),
    }


def _clean(sel: list[dict]) -> list[dict]:
    return [
        r for r in sel if not r["ambiguous"] and "possible_corporate_action" not in (r["trade_flags"] or [])
    ]


def group_series(rows: list[dict]) -> dict:
    """The daily edges the verdict is made from, plus the picks' average net return."""
    scored = [r for r in rows if r["status"] == "scored"]
    # U2: a day counts as evidence only if the group had enough eligible stocks that day
    need = P.RUN_VALUES["min_evidence_per_group"]["min_eligible_per_day"]
    per_day = Counter(r["signal_day"] for r in scored)
    scored = [r for r in scored if per_day[r["signal_day"]] >= need]
    counted = [r for r in scored if r["selected"] and not r["repeat_blocked"]]
    pool_label = _by_day([r for r in scored if r["label_status"] == "evaluated"], lambda r: r["label_hit"])
    pick_label = _by_day([r for r in counted if r["label_status"] == "evaluated"], lambda r: r["label_hit"])
    done_pool = [r for r in scored if r["trade_status"] in RESOLVED and r["net_return"] is not None]
    done_ids = {id(r) for r in done_pool}
    pool_trade = _by_day(done_pool, lambda r: r["net_return"])
    pick_rows = [r for r in counted if id(r) in done_ids]
    pick_trade = _by_day(pick_rows, lambda r: r["net_return"])
    return {
        # selection: the picks minus every eligible stock, per matured signal day
        "trade_edge": _daily_edge(pick_trade, pool_trade),
        "label_edge": _daily_edge(pick_label, pool_label),
        # economic: the picks' own average net return per matured signal day (no baseline)
        "picks_daily_net": [fmean(pick_trade[d]) for d in sorted(pick_trade) if pick_trade[d]],
        "picks_mean_net": _mean([r["net_return"] for r in pick_rows]),
        "pool_trade": pool_trade,
    }


def _membership(scored: list[dict], flag: bool) -> dict:
    sub = [r for r in scored if bool(r["trained_on_symbol"]) is flag]
    picks = [r for r in sub if r["selected"] and not r["repeat_blocked"]]
    return {
        "stocks_day_rows": len(sub),
        "distinct_stocks": len({r["symbol"] for r in sub}),
        "counted_picks": len(picks),
        "endpoint_label": {"picks": _endpoint(picks), "every_eligible_stock_in_this_subset": _endpoint(sub)},
        "shadow_trade": {"picks": _trade(picks), "every_eligible_stock_in_this_subset": _trade(sub)},
    }


def _top5_overlap(df: pd.DataFrame) -> int:
    def top(col: str) -> set:
        return set(df.sort_values([col, "s"], ascending=[False, True]).head(P.TOP_K)["s"])

    return len(top("a") & top("b"))


def _gap_between_scores(scored: list[dict]) -> dict:
    """How far the production-path score (today's obv_slope formula, 400 bars) sits from the primary score."""
    by_day: dict = defaultdict(list)
    for r in scored:
        if r["score_production_path"] is not None:
            by_day[r["signal_day"]].append(r)
    corr, overlap = [], []
    for rows in by_day.values():
        if len(rows) < 6:
            continue
        df = pd.DataFrame(
            {
                "a": [r["score"] for r in rows],
                "b": [r["score_production_path"] for r in rows],
                "s": [r["symbol"] for r in rows],
            }
        )
        corr.append(float(df["a"].rank().corr(df["b"].rank())))
        overlap.append(_top5_overlap(df))
    return {
        "days": len(corr),
        "mean_rank_correlation": _mean(corr),
        "mean_top5_overlap": _mean(overlap),
        "note": "the primary score decides every selection; the production-path score never does",
    }


def summarise_group(rows: list[dict]) -> dict:
    """`rows`: one dict per stock per signal day for ONE group of ONE run."""
    scored = [r for r in rows if r["status"] == "scored"]
    counted = [r for r in scored if r["selected"] and not r["repeat_blocked"]]
    every_selection = [r for r in scored if r["selected"]]
    series = group_series(rows)
    rand = R.random_k_distribution(list(series["pool_trade"].values()))
    pick_mean = _trade(counted)["mean_net_return"]
    lo_i, hi_i = int(0.05 * len(rand)), max(0, int(0.95 * len(rand)) - 1)
    ns = Counter((r["symbol"], r["not_scored_reason"]) for r in rows if r["status"] != "scored")
    return {
        "signal_days": len({r["signal_day"] for r in rows}),
        "scored": len(scored),
        "not_scored": dict(Counter(r["not_scored_reason"] for r in rows if r["status"] != "scored")),
        "not_scored_events": [
            {"symbol": s, "reason": why, "days": n}
            for (s, why), n in sorted(ns.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "selected": len(every_selection),
        "counted_selections": len(counted),
        "repeat_not_counted": len(every_selection) - len(counted),
        "selected_trained_on_symbol": sum(1 for r in counted if r["trained_on_symbol"]),
        "endpoint_label": {
            "question": "did the close 5 sessions after the signal reach +2% above the signal close?",
            "reference_price": "signal close",
            "counted_picks": _endpoint(counted),
            "every_selection": _endpoint(every_selection),
            "baseline_every_eligible_stock": _endpoint(scored),
            "daily_edge_vs_baseline": _range(series["label_edge"]),
        },
        "shadow_trade": {
            "rule": "+2% target / -4% stop / at most 5 sessions, entry at the next open, frozen costs",
            "reference_price": "executable entry fill",
            "counted_picks": _trade(counted),
            "every_selection": _trade(every_selection),
            "counted_picks_without_flagged": _trade(_clean(counted)),
            "baseline_every_eligible_stock": _trade(scored),
            "random_5_same_days_5th_to_95th_percentile": [rand[lo_i], rand[hi_i]] if rand else None,
            "picks_vs_random_note": None
            if pick_mean is None or not rand
            else "picks average is above the random range"
            if pick_mean > rand[hi_i]
            else "picks average is below the random range"
            if pick_mean < rand[lo_i]
            else "picks average is inside the random range",
            "daily_edge_vs_baseline": _range(series["trade_edge"]),
            "daily_picks_net_return": _range(series["picks_daily_net"]),
            "higher_cost_sensitivity": {
                "assumption": f"every fill {P.STRESS['extra_slip_bps']:g} bps worse and charges x{P.STRESS['charges_x']:g}; never decides a verdict",
                "counted_picks": _trade(counted, "net_return_stress", "trade_status_stress"),
                "baseline_every_eligible_stock": _trade(scored, "net_return_stress", "trade_status_stress"),
            },
        },
        "diagnostics": {
            "note": DIAGNOSTIC_NOTE,
            "training_membership": {
                "in_training": _membership(scored, True),
                "not_in_training": _membership(scored, False),
            },
            "production_path_score_gap": _gap_between_scores(scored),
        },
        "pending_outcomes": sum(
            1 for r in scored if r["label_status"] == "pending" or r["trade_status"] == "pending"
        ),
    }


def _row(s: H05Signal) -> dict:
    return {
        c: getattr(s, c)
        for c in (
            "signal_day",
            "symbol",
            "group",
            "status",
            "not_scored_reason",
            "score",
            "score_production_path",
            "selected",
            "repeat_blocked",
            "trained_on_symbol",
            "label_status",
            "label_hit",
            "trade_status",
            "net_return",
            "trade_status_stress",
            "net_return_stress",
            "ambiguous",
            "gap_fill",
            "trade_flags",
        )
    }


def _verdicts(db_runs: list[dict]) -> dict:
    """Per group: each run's two verdicts (selection, economic), then the two combined verdicts.
    Only called once the protocol is accepted. A run that is open or has unmatured outcomes is not final."""
    out: dict = {}
    for g in P.GROUPS:
        finals, pooled_edge, pooled_net = [], [], []
        entry = out.setdefault(g, {"runs": {}})
        for run in db_runs:
            info = run["groups"][g]
            ser = run["_series"][g]
            if run["status"] != "closed" or info["pending_outcomes"]:
                waiting = {"verdict": V.INCONCLUSIVE, "range": None}
                entry["runs"][run["run_no"]] = {
                    "selection": waiting,
                    "economic": waiting,
                    "why": "waiting: run not closed"
                    if run["status"] != "closed"
                    else f"waiting: {info['pending_outcomes']} outcomes not matured",
                    "final": False,
                }
                continue
            dec = V.run_decision(
                ser["trade_edge"], ser["label_edge"], ser["picks_daily_net"], run["_shortfall_share"][g]
            )
            entry["runs"][run["run_no"]] = {**dec, "final": True}
            finals.append(dec)
            pooled_edge += ser["trade_edge"]
            pooled_net += ser["picks_daily_net"]
        entry["combined"] = V.combined_decision(finals, pooled_edge, pooled_net)
    return out


def build_report(db: Session, run_no: int | None = None, now: datetime | None = None) -> dict:
    from swing_trade_ml.brain.lanes.h05_service import market_sessions

    all_runs = db.execute(select(H05Run).order_by(H05Run.run_no)).scalars().all()
    runs = [r for r in all_runs if run_no is None or r.run_no == run_no]
    sessions = market_sessions(db)
    closed_through = last_closed_trading_day(now or datetime.now(UTC))  # a session still open is not 'missed'
    out_runs = []
    for run in runs:
        rows = [_row(s) for s in db.execute(select(H05Signal).where(H05Signal.run_id == run.id)).scalars()]
        gdays = db.execute(select(H05GroupDay).where(H05GroupDay.run_id == run.id)).scalars().all()
        events = (
            db.execute(select(H05Event).where(H05Event.run_id == run.id).order_by(H05Event.id))
            .scalars()
            .all()
        )
        recorded = {d.signal_day for d in gdays}
        expected = [d for d in sessions if run.start_day <= d <= min(run.end_day, closed_through)]
        groups, series, shortfall = {}, {}, {}
        for g in P.GROUPS:
            grows = [r for r in rows if r["group"] == g]
            groups[g] = {
                **summarise_group(grows),
                "days_with_shortfall": sum(1 for d in gdays if d.group == g and d.shortfall > 0),
                "total_shortfall": sum(d.shortfall for d in gdays if d.group == g),
            }
            series[g] = group_series(grows)
            gd = [d for d in gdays if d.group == g]
            shortfall[g] = (sum(1 for d in gd if d.shortfall > 0) / len(gd)) if gd else 0.0
        out_runs.append(
            {
                "run_no": run.run_no,
                "status": run.status,
                "start_day": str(run.start_day),
                "end_day": str(run.end_day),
                "protocol_code": run.protocol_code,
                "protocol_hash": run.protocol_hash,
                "models": run.models,
                "feature_parity": run.parity,
                "universe_hash": run.universe_hash,
                "universe_excluded": run.universe["excluded"],
                "days_recorded": len(recorded),
                "days_missed": [str(d) for d in expected if d not in recorded],
                # why each unrecorded session was missed (saved once by the daily job); never made up later
                "missed_sessions": [
                    {"signal_day": str(e.signal_day), "reason": e.detail}
                    for e in events
                    if e.kind == "missed_session"
                ],
                "sessions_in_window": len(expected),
                "events": [
                    {
                        "at": str(e.created_at),
                        "signal_day": str(e.signal_day),
                        "kind": e.kind,
                        "detail": e.detail,
                    }
                    for e in events
                ],
                "data_provenance_days": len({d.signal_day for d in gdays if d.provenance}),
                "groups": groups,
                "_series": series,
                "_shortfall_share": shortfall,
            }
        )
    accepted = P.accepted()
    verdict = _verdicts(out_runs) if accepted and out_runs else None
    for r in out_runs:
        r.pop("_series")
        r.pop("_shortfall_share")
    return {
        "title": P.PAGE_LABEL,
        "protocol_code": P.PROTOCOL_CODE,
        "protocol_hash": P.protocol_hash(),
        "protocol_accepted": accepted,
        "runs": out_runs,
        "verdict": verdict if verdict is not None else {"state": "not_calculated", "why": NO_VERDICT},
        "verdict_note": "calculated mechanically from the frozen rule" if verdict is not None else NO_VERDICT,
        "scoring_label": P.SCORING_LABEL,
        "assumptions": [P.SLIPPAGE_STATUS, P.COST_UNITS["net_return"], P.COST_UNITS["slippage"]],
        "score_note": SCORE_NOTE,
        "execution_note": P.EXECUTION_NOTE,
        "earlier_evidence": P.EARLIER_EVIDENCE,
        "unresolved": [list(u) for u in P.UNRESOLVED],
        "differences_from_v1": P.VERSION_DIFFERENCES_FROM_V1,
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.2f}%"


def render_markdown(report: dict) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"Protocol `{report['protocol_code']}` · hash `{report['protocol_hash'][:16]}` · accepted: {report['protocol_accepted']}",
        "",
        f"> {report['scoring_label']}",
        f"> {report['verdict_note']}",
        f"> {report['score_note']}",
        f"> {report['execution_note']}",
        *[f"> ASSUMPTION: {a}" for a in report["assumptions"]],
        "",
        f"**Earlier 5-day test stays on record:** {report['earlier_evidence']['result']} ({report['earlier_evidence']['source']}).",
        "",
    ]
    for run in report["runs"]:
        lines += [f"## Run {run['run_no']} ({run['status']}) · {run['start_day']} to {run['end_day']}", ""]
        lines += [
            f"- days recorded {run['days_recorded']} of {run['sessions_in_window']} sessions · not recorded {len(run['days_missed'])} {run['days_missed'][:10] or ''} (never made up; the run is not extended)",
            *[f"  - MISSED {m['signal_day']}: {m['reason']}" for m in run["missed_sessions"]],
            f"- universe exclusions (never scored): {run['universe_excluded'] or 'none'}",
        ]
        for e in run["events"]:
            lines.append(f"- EVENT {e['at']} {e['kind']} ({e['signal_day']}): {e['detail']}")
        lines.append("")
        for g, s in run["groups"].items():
            e, t = s["endpoint_label"], s["shadow_trade"]
            d = s["diagnostics"]["training_membership"]
            lines += [
                f"### {g} cap",
                f"- signal days {s['signal_days']} · scored {s['scored']} · counted picks {s['counted_selections']} "
                f"(repeats not counted {s['repeat_not_counted']}) · days with a short top 5: {s['days_with_shortfall']}",
                f"- NOT SCORED: {s['not_scored'] or 'none'}",
                *[
                    f"  - {x['symbol']}: {x['reason']} ({x['days']} days)"
                    for x in s["not_scored_events"][:20]
                ],
                f"- endpoint label (+2% after 5 sessions, from the signal close): picks {_pct(e['counted_picks']['hit_rate'])} "
                f"(n={e['counted_picks']['n']}) vs every eligible stock {_pct(e['baseline_every_eligible_stock']['hit_rate'])} "
                f"(n={e['baseline_every_eligible_stock']['n']})",
                f"- shadow trade (net of costs, from the entry fill): picks {_pct(t['counted_picks']['mean_net_return'])} "
                f"(finished {t['counted_picks']['finished']}) vs every eligible stock "
                f"{_pct(t['baseline_every_eligible_stock']['mean_net_return'])}; {t['picks_vs_random_note'] or 'no random yardstick yet'}",
                f"- higher-cost sensitivity: picks {_pct(t['higher_cost_sensitivity']['counted_picks']['mean_net_return'])} "
                f"vs every eligible stock {_pct(t['higher_cost_sensitivity']['baseline_every_eligible_stock']['mean_net_return'])}",
                f"- exits {t['counted_picks']['exits']} · ambiguous {t['counted_picks']['ambiguous_same_candle']} · "
                f"unresolved {t['counted_picks']['unresolved']}",
                f"- {s['diagnostics']['note']} In training: {d['in_training']['distinct_stocks']} stocks, picks "
                f"{_pct(d['in_training']['shadow_trade']['picks']['mean_net_return'])}; not in training: "
                f"{d['not_in_training']['distinct_stocks']} stocks, picks {_pct(d['not_in_training']['shadow_trade']['picks']['mean_net_return'])}",
                "",
            ]
    v = report["verdict"]
    if report["protocol_accepted"] and "state" not in v:
        lines += ["## Verdict (frozen rule, calculated mechanically)"]
        for g, info in v.items():
            c = info["combined"]
            lines.append(
                f"- {g}: SELECTION {c['selection']['verdict']} (runs "
                + str({k: x["selection"]["verdict"] for k, x in info["runs"].items()})
                + f") · ECONOMIC {c['economic']['verdict']} (runs "
                + str({k: x["economic"]["verdict"] for k, x in info["runs"].items()})
                + f") · {c['reading']}"
            )
        lines.append("")
    lines += [
        "## Differences from the v1 bot",
        *[f"- {d}" for d in report["differences_from_v1"]],
        "",
        "## Choices (confirmed by accepting the protocol hash)",
        *[f"- {u[0]}: {u[1]} ({u[2]})" for u in report["unresolved"]],
        "",
    ]
    return "\n".join(lines)
