# backend/src/swing_trade_ml/brain/lanes/h05_cli.py
# ruff: noqa: N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""Command line for the h05 lane:  python -m swing_trade_ml.brain.lanes.h05_cli <command>

Read-only commands (always allowed): protocol, check, parity, preview, power.
Writing commands (refused unless the lane is enabled, complete and accepted): start-run, score,
evaluate, close-run, daily, report --save.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_report, h05_service
from swing_trade_ml.brain.lanes.h05_models import build_universe, verify_models
from swing_trade_ml.core.config import REPO_ROOT
from swing_trade_ml.db.models.lanes import H05Run
from swing_trade_ml.db.session import session_scope


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _run(db, run_no: int) -> H05Run:
    run = db.scalar(select(H05Run).where(H05Run.run_no == run_no))
    if run is None:
        raise P.ProtocolError(f"run {run_no} does not exist")
    return run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="h05", description=P.PAGE_LABEL)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("protocol", help="print the protocol hash, what is unresolved and whether it is accepted")
    sub.add_parser("check", help="read-only: verify the three frozen models and build the universe")
    sub.add_parser(
        "parity",
        help="read-only: does today's feature code reproduce each saved scaler on its training data?",
    )
    p = sub.add_parser("preview", help="read-only: score one signal day, store nothing")
    p.add_argument("--signal-day", type=_day, required=True)
    p = sub.add_parser(
        "power",
        help="read-only: simulate the frozen decision procedure on local history",
    )
    p.add_argument("--replicates", type=int, default=1000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--quick", action="store_true", help="only run length 60 for the power grid")
    p.add_argument("--out", type=Path, help="write <out>.json and <out>.md")
    sub.add_parser(
        "daily", help="one pass of the daily job: record the latest session, report misses, mature outcomes"
    )
    p = sub.add_parser("start-run")
    p.add_argument("--run-no", type=int, required=True)
    p.add_argument("--start", type=_day, required=True)
    p.add_argument("--end", type=_day, required=True)
    for name in ("score", "evaluate", "close-run"):
        p = sub.add_parser(name)
        p.add_argument("--run-no", type=int, required=True)
        if name == "score":
            p.add_argument("--signal-day", type=_day, required=True)
    p = sub.add_parser("report")
    p.add_argument("--run-no", type=int)
    p.add_argument("--save", action="store_true", help=f"write markdown + json under {P.EVIDENCE_DIR}/")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "protocol":
            s = P.H05Settings()
            print(
                json.dumps(
                    {
                        "protocol_code": P.PROTOCOL_CODE,
                        "protocol_hash": P.protocol_hash(),
                        "enabled": s.ENABLED,
                        "accepted": P.protocol_hash() == s.ACCEPTED_PROTOCOL_HASH,
                        "missing_values": P.missing_values(),
                        "unresolved": [list(u) for u in P.UNRESOLVED],
                    },
                    indent=2,
                )
            )
            return 0
        with session_scope() as db:
            if a.cmd == "check":
                models = verify_models(db)
                universe, excluded, digest = build_universe(db)
                print(
                    json.dumps(
                        {
                            "models": {g: m.identity() for g, m in models.items()},
                            "universe": {g: sum(1 for v in universe.values() if v == g) for g in P.GROUPS},
                            "universe_in_model_training": {
                                g: sum(
                                    1
                                    for s, v in universe.items()
                                    if v == g and s in models[g].training_symbols
                                )
                                for g in P.GROUPS
                            },
                            "excluded": excluded,
                            "universe_hash": digest,
                        },
                        indent=2,
                        default=str,
                    )
                )
            elif a.cmd == "parity":
                from swing_trade_ml.brain.lanes.h05_parity import parity_report

                print(json.dumps(parity_report(db, verify_models(db)), indent=2, default=str))
            elif a.cmd == "power":
                from swing_trade_ml.brain.lanes import h05_power

                rep = h05_power.full_report(h05_power.build_table(db), a.replicates, a.seed, a.quick)
                text = h05_power.render_markdown(rep)
                print(text)
                if a.out:
                    a.out.parent.mkdir(parents=True, exist_ok=True)
                    a.out.with_suffix(".json").write_text(h05_power.dump(rep), encoding="utf-8")
                    a.out.with_suffix(".md").write_text(text, encoding="utf-8")
            elif a.cmd == "preview":
                models = verify_models(db)
                universe, excluded, _ = build_universe(db)
                _, _, summary = h05_service.preview_day(
                    db, {"groups": universe, "excluded": excluded}, a.signal_day, models
                )
                print(
                    json.dumps(
                        {"signal_day": str(a.signal_day), "summary": summary, "stored": False}, indent=2
                    )
                )
            elif a.cmd == "daily":
                from swing_trade_ml.brain.lanes import h05_job

                result = h05_job.run_daily(db)
                print(json.dumps(result, indent=2, default=str))
                if any(x.get("state") == "lane_stopped" for x in result.get("actions", [])):
                    return 3
            elif a.cmd == "start-run":
                run = h05_service.start_run(db, a.run_no, a.start, a.end)
                print(f"run {run.run_no} created {run.start_day} to {run.end_day}")
            elif a.cmd == "score":
                result = h05_service.score_day(db, _run(db, a.run_no), a.signal_day)
                print(json.dumps(result, indent=2))
                if result.get("stopped"):
                    print("LANE STOPPED for this day: the reason is saved as an event.", file=sys.stderr)
                    return 3
            elif a.cmd == "evaluate":
                print(json.dumps(h05_service.evaluate(db, _run(db, a.run_no))))
            elif a.cmd == "close-run":
                h05_service.close_run(db, _run(db, a.run_no))
                print("closed")
            elif a.cmd == "report":
                report = h05_report.build_report(db, a.run_no)
                text = h05_report.render_markdown(report)
                print(text)
                if a.save:
                    P.require_runnable()
                    out = Path(REPO_ROOT / P.EVIDENCE_DIR)
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "report.md").write_text(text, encoding="utf-8")
                    (out / "report.json").write_text(
                        json.dumps(report, indent=2, default=str), encoding="utf-8"
                    )
    except P.ProtocolError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
