# ruff: noqa: E501 (long lines are report sentences)
"""Weekly training-eligibility report. READ-ONLY: it trains nothing, writes nothing, calls no network.

For each tracked lane it answers: how many outcomes have matured, how many the lane's protocol needs, the
earliest allowed date, whether a protocol gate (date, tag, signature, authorisation) blocks, and one verdict word.

Verdicts
  OBSERVE_ONLY            the lane is an evaluation: the protocol never lets it train a candidate.
  ELIGIBLE_NOT_AUTHORISED every gate this report can check is met; the owner's own step is still needed.
  BLOCKED_BY_PROTOCOL     at least one protocol gate (date / tag / signature) is not met.
  NOT_APPLICABLE          the lane has no slot (10D is deferred).

Seal. Only COUNTS are read: for h05 the query selects group, day and status columns, never a return, hit or
score, so the sealed trial (services/trial_seal.py) and the lane's own results stay unseen. The 15D lab and SX5
are history evaluations with no forward picks, so their matured count is reported as "n/a", never guessed.

Thresholds are READ from code, not invented: h05 from `lanes.h05_protocol.RUN_VALUES` (U2) and
`lanes.h05_report.RESOLVED`; 15D from `selection_lab_start` / `selection_lab_run`; SX5 from `scripts/sx5_run.py`
(EARLIEST_REAL_DATE; scripts/ is not importable, so it is mirrored below and a test compares the two).

Run:  python -m swing_trade_ml.brain.eligibility_report
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
VERDICTS = ("OBSERVE_ONLY", "ELIGIBLE_NOT_AUTHORISED", "BLOCKED_BY_PROTOCOL", "NOT_APPLICABLE")

# Mirrors of protocol constants; tests/test_eligibility_report.py compares each with its source.
H05_MIN_MATURED_DAYS = 40  # h05_protocol.RUN_VALUES["min_evidence_per_group"]["matured_signal_days"] (U2)
H05_MIN_ELIGIBLE = 10  # ... ["min_eligible_per_day"]
H05_RESOLVED = ("target", "stop", "expiry")  # h05_report.RESOLVED
LAB_EARLIEST = date(2026, 12, 5)  # selection_lab_start.EARLIEST_START (Amendment 2, item 2)
SX5_EARLIEST = date(2026, 12, 4)  # scripts/sx5_run.py EARLIEST_REAL_DATE
AMENDMENT3_SIGNED_FILE = (
    "docs/brain/evidence/sl_v1/EVIDENCE_PLAN_AMENDMENT_3_SIGNED.md"  # selection_lab_run.AMENDMENT
)


def count_h05_matured(rows: Sequence[dict], group: str) -> dict:
    """Pure. A signal day is MATURED for a group when >= 10 stocks were scored that day and at least one
    counted pick (selected, not a repeat) has a finished shadow trade (target / stop / expiry). Same rule as
    `h05_report.group_series`, but on status columns only. Needs keys: group, signal_day, status, selected,
    repeat_blocked, trade_status."""
    scored = [r for r in rows if r["group"] == group and r["status"] == "scored"]
    per_day = Counter(r["signal_day"] for r in scored)
    days = {d for d, n in per_day.items() if n >= H05_MIN_ELIGIBLE}
    matured_picks = [
        r
        for r in scored
        if r["signal_day"] in days
        and r["selected"]
        and not r["repeat_blocked"]
        and r["trade_status"] in H05_RESOLVED
    ]
    return {
        "signal_days": len(per_day),
        "matured_days": len({r["signal_day"] for r in matured_picks}),
        "counted_picks_matured": len(matured_picks),
    }


def _lane(lane: str, **kw) -> dict:
    base = {
        "lane": lane,
        "matured": None,
        "needed": None,
        "needed_source": "",
        "earliest_date": None,
        "blocking": [],
        "evidence_met": None,
        "verdict": "NOT_APPLICABLE",
        "note": "",
    }
    base.update(kw)
    return base


def _h05(group: str, facts: dict) -> dict:
    gates = [
        ("h05 lane enabled", facts.get("h05_enabled")),
        ("protocol hash accepted by owner", facts.get("h05_accepted")),
        ("run 1 started", facts.get("h05_run_started")),
    ]
    rows = facts.get("h05_rows")
    if rows is None:
        matured, met, extra = None, None, " Database unavailable: matured count unknown (not zero)."
    else:
        c = count_h05_matured(rows, group)
        matured = c["matured_days"]
        met = matured >= H05_MIN_MATURED_DAYS
        extra = f" {c['counted_picks_matured']} counted picks finished across {c['signal_days']} recorded signal days."
    return _lane(
        f"5D {group}",
        matured=matured,
        needed=H05_MIN_MATURED_DAYS,
        needed_source="h05_protocol.RUN_VALUES U2: 40 matured signal days per group per run (docs/superpowers/specs/2026-10-30-h05-protocol-v1-DRAFT.md, U2)",
        blocking=[name for name, ok in gates if not ok],
        evidence_met=met,
        verdict="OBSERVE_ONLY",
        note="Evaluation of the existing production model; the protocol forbids retraining, calibration or activation (h05_protocol docstring). Matured = signal days, not picks."
        + extra,
    )


def _lab(group: str, today: date, facts: dict) -> dict:
    tags = facts.get("tags") or set()
    blocking = []
    if today < LAB_EARLIEST:
        blocking.append(f"not before {LAB_EARLIEST} (IST)")
    if "phase-b-result" not in tags:
        blocking.append("annotated tag phase-b-result")
    if "sl-protocol-v1.1" not in tags:
        blocking.append("tag sl-protocol-v1.1")
    if not facts.get("amendment3_signed"):
        blocking.append("Amendment 3 signed marker")
    cands = (
        "S0/S1/S2 (the 49 large stocks)"
        if group == "large"
        else "S0M/S1M/S2M (14-stock mid group, limited experiment)"
    )
    return _lane(
        f"15D {group}",
        earliest_date=str(LAB_EARLIEST),
        needed_source="selection_lab_start.EARLIEST_START + selection_lab_run guard (Amendment 3; docs/brain/SELECTION-LAB-START.md)",
        blocking=blocking,
        verdict="BLOCKED_BY_PROTOCOL" if blocking else "ELIGIBLE_NOT_AUTHORISED",
        note=f"n/a: history evaluation of {cands}, no forward picks, so no matured count. The owner starts it through selection_lab_start, which also checks the Phase B record, clean tree, frozen files and gap classification (not checked here).",
    )


def build_report(today: date, facts: dict) -> dict:
    """Pure. `today` is an IST date; `facts` holds already-read inputs (keys used above)."""
    sx5_blocking = [f"not before {SX5_EARLIEST} (IST)"] if today < SX5_EARLIEST else []
    lanes = [
        _h05("large", facts),
        _h05("mid", facts),
        _h05("small", facts),
        _lane(
            "10D",
            verdict="NOT_APPLICABLE",
            needed_source="docs/brain/PROJECT_COMPLETION_MATRIX.md (10D deferred); docs/brain/evidence/td_v1 (td-protocol-v1 failed)",
            note="No slot, deferred by the owner after td-protocol-v1 failed its history gate; no retrain, no td-protocol-v2.",
        ),
        _lab("large", today, facts),
        _lab("mid", today, facts),
        _lane(
            "SX5",
            earliest_date=str(SX5_EARLIEST),
            needed_source="scripts/sx5_run.py EARLIEST_REAL_DATE; docs/brain/SX5-RUN.md",
            blocking=sx5_blocking,
            verdict="BLOCKED_BY_PROTOCOL" if sx5_blocking else "ELIGIBLE_NOT_AUTHORISED",
            note="n/a: development-only walk-forward, no forward picks. Needs the signed protocol, a signing tag, the approval file and a SEPARATE training authorisation (sx5-training-authorisation-v1). This report cannot see those, so authorisation is never assumed.",
        ),
    ]
    return {"as_of": str(today), "trains_nothing": True, "lanes": lanes}


def render_text(report: dict) -> str:
    out = [
        f"Training-eligibility report as of {report['as_of']} (IST). Read-only: trains nothing, writes nothing.",
        "Counts only; no returns, rates or sealed trial results are read.",
        "",
    ]
    for x in report["lanes"]:
        m = "n/a" if x["matured"] is None else str(x["matured"])
        n = "n/a" if x["needed"] is None else str(x["needed"])
        out.append(f"{x['lane']:<9} {x['verdict']}")
        out.append(f"    matured {m} / needed {n}   earliest date: {x['earliest_date'] or 'n/a'}")
        out.append(f"    blocking: {', '.join(x['blocking']) or 'none'}")
        out.append(f"    source: {x['needed_source'] or 'n/a'}")
        out.append(f"    note: {x['note']}")
        out.append("")
    return "\n".join(out)


# ---- reading (CLI only; read-only) ---------------------------------------------------------------


def _git_tags(repo: Path) -> set[str]:
    try:
        r = subprocess.run(
            ["git", "tag", "--list"], cwd=repo, capture_output=True, text=True, timeout=30, check=False
        )
        return set(r.stdout.split()) if r.returncode == 0 else set()
    except (OSError, subprocess.SubprocessError):
        return set()


def _amendment3_signed(repo: Path) -> bool:
    p = repo / AMENDMENT3_SIGNED_FILE
    try:
        return p.is_file() and any(
            line.lstrip().upper().startswith("SIGNED") for line in p.read_text(encoding="utf-8").splitlines()
        )
    except OSError:
        return False


def read_facts() -> dict:
    """Gather inputs. One SELECT of status columns on the h05 tables; nothing else touches the database."""
    from sqlalchemy import func, select

    from swing_trade_ml.brain.lanes import h05_protocol as proto
    from swing_trade_ml.core.config import REPO_ROOT
    from swing_trade_ml.db.models.lanes import H05Run, H05Signal
    from swing_trade_ml.db.session import SessionLocal

    s = proto.H05Settings()
    facts: dict = {
        "h05_enabled": bool(s.ENABLED),
        "h05_accepted": bool(proto.accepted(s)),
        "tags": _git_tags(REPO_ROOT),
        "amendment3_signed": _amendment3_signed(REPO_ROOT),
        "h05_rows": None,
        "h05_run_started": False,
    }
    try:
        with SessionLocal() as db:
            facts["h05_run_started"] = (db.scalar(select(func.count()).select_from(H05Run)) or 0) > 0
            q = select(
                H05Signal.group,
                H05Signal.signal_day,
                H05Signal.status,
                H05Signal.selected,
                H05Signal.repeat_blocked,
                H05Signal.trade_status,
            )
            facts["h05_rows"] = [
                {
                    "group": g,
                    "signal_day": d,
                    "status": st,
                    "selected": bool(sel),
                    "repeat_blocked": bool(rb),
                    "trade_status": ts,
                }
                for g, d, st, sel, rb, ts in db.execute(q).all()
            ]
    except Exception:  # noqa: BLE001 - any database trouble means "unknown", never a guess
        facts["h05_rows"] = None
    return facts


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Weekly training-eligibility report (read-only)")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    a = p.parse_args(argv)
    report = build_report(datetime.now(IST).date(), read_facts())
    print(json.dumps(report, indent=2) if a.json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
