"""ps7: pre-set rules that put the brain back into practice by themselves.

Once the owner has moved the brain to the approval or automatic stage, these rules are checked after each
trading day's daily check (workers/jobs.py::job_brain_daily_check). If any one is crossed, the stage goes
back to practice (shadow) through `stage.set_stage`, exactly as the owner's own rollback does: ideas
waiting for an OK expire, nothing new is bought, positions already held keep version 1's exits.

The rules can only ever step the brain BACK. They never move it forward, never touch real-money code,
and do nothing while the brain is already in practice, so the forward trial (practice stage) is
unaffected.

Every rule is off (0) until the owner sets its number (settings, see core/config.py):

* BRAIN_PAUSE_LOSING_STREAK         -- this many finished brain ideas in a row lost money.
* BRAIN_PAUSE_BEHIND_AFTER_IDEAS    -- once this many brain ideas have finished since the brain left
                                       practice, it is behind "buying every stock" (trial journal gate).
* BRAIN_PAUSE_FAILED_NIGHTLY_RUNS   -- this many live nightly brain runs in a row failed.

If the rules are switched on but cannot be checked (a read fails), the brain is paused too: a check that
cannot be done is treated like a crossed one, never as a pass.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import BrainRun
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.services import trial_seal

log = get_logger(__name__)

PAUSE_BY = "pause rule"
SEALED_REASON = "A pre-set pause rule was crossed (details sealed until the trial's evaluation)."


@dataclass(frozen=True, slots=True)
class PauseRules:
    losing_streak: int = 0
    behind_after_ideas: int = 0
    failed_nightly_runs: int = 0

    @property
    def any_on(self) -> bool:
        return self.losing_streak > 0 or self.behind_after_ideas > 0 or self.failed_nightly_runs > 0


def rules_from_settings() -> PauseRules:
    return PauseRules(
        losing_streak=max(int(settings.BRAIN_PAUSE_LOSING_STREAK or 0), 0),
        behind_after_ideas=max(int(settings.BRAIN_PAUSE_BEHIND_AFTER_IDEAS or 0), 0),
        failed_nightly_runs=max(int(settings.BRAIN_PAUSE_FAILED_NIGHTLY_RUNS or 0), 0),
    )


# --- pure ---------------------------------------------------------------------------------------


def trailing_losses(outcomes: Sequence[float | None]) -> int:
    """How many of the newest finished results, oldest first in `outcomes`, lost money in a row."""
    n = 0
    for pct in reversed(outcomes):
        if pct is None or pct >= 0:
            break
        n += 1
    return n


def trailing_failures(statuses: Sequence[str]) -> int:
    """How many of the newest nightly runs, newest first in `statuses`, failed in a row."""
    n = 0
    for status in statuses:
        if status != "failed":
            break
        n += 1
    return n


def crossed(rules: PauseRules, *, streak: int, gate: dict | None, failed_runs: int) -> list[str]:
    """Plain-English reasons for every rule crossed; empty means keep going."""
    reasons = []
    if rules.losing_streak and streak >= rules.losing_streak:
        reasons.append(f"{streak} brain ideas in a row lost money (pause rule: {rules.losing_streak}).")
    if rules.behind_after_ideas and gate is not None:
        finished = int(gate.get("finished") or 0)
        if finished >= rules.behind_after_ideas and not gate.get("beats_random"):
            reasons.append(
                f"After {finished} finished ideas since leaving practice, the brain is behind buying every "
                f"stock (pause rule: check after {rules.behind_after_ideas})."
            )
    if rules.failed_nightly_runs and failed_runs >= rules.failed_nightly_runs:
        reasons.append(
            f"{failed_runs} nightly brain runs in a row failed (pause rule: {rules.failed_nightly_runs})."
        )
    return reasons


# --- reading the database -----------------------------------------------------------------------


def _left_practice_on(db: Session) -> date | None:
    """The day of the newest change out of practice, or None if the brain is in practice now."""
    row = db.execute(select(BrainStageChange).order_by(BrainStageChange.id.desc()).limit(1)).scalar_one_or_none()
    if row is None or row.stage not in ("approval", "auto"):
        return None
    out = row
    while out is not None and out.previous_stage in ("approval", "auto"):
        # approval -> auto keeps the same "since": count from the step out of practice.
        out = db.execute(
            select(BrainStageChange)
            .where(BrainStageChange.id < out.id)
            .order_by(BrainStageChange.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    first = out or row
    from swing_trade_ml.brain.trial_journal import IST

    return (first.changed_at or datetime.now(IST)).astimezone(IST).date()


def _brain_outcomes_since(db: Session, since: date) -> list[float | None]:
    from swing_trade_ml.services.brain_golive.compare import load, one_per_day

    rows, _ = load(db, since)
    return [r.outcome_pct for r in one_per_day(rows) if r.is_brain and not r.blocked and r.outcome is not None]


def _nightly_statuses(db: Session, limit: int) -> list[str]:
    return list(
        db.execute(
            select(BrainRun.status)
            .where(
                BrainRun.kind == "nightly",
                BrainRun.live.is_(True),
                BrainRun.status.in_(("done", "failed")),
            )
            .order_by(BrainRun.as_of.desc())
            .limit(limit)
        ).scalars()
    )


def evaluate(db: Session, rules: PauseRules | None = None, today: date | None = None) -> dict:
    """Read-only: which rules are crossed right now. Never raises."""
    from swing_trade_ml.services.brain_golive.stage import current_stage

    rules = rules or rules_from_settings()
    stage = current_stage(db)
    out: dict = {"stage": stage, "rules_on": rules.any_on, "reasons": []}
    if stage not in ("approval", "auto") or not rules.any_on:
        return out
    try:
        since = _left_practice_on(db)
        if since is None:
            return out
        streak = trailing_losses(_brain_outcomes_since(db, since)) if rules.losing_streak else 0
        gate = None
        if rules.behind_after_ideas:
            from swing_trade_ml.brain.trial_journal import IST, journal_for

            end = today or datetime.now(IST).date()
            gate = journal_for(db, since, max(end, since))["gate"]
        failed = (
            trailing_failures(_nightly_statuses(db, rules.failed_nightly_runs))
            if rules.failed_nightly_runs
            else 0
        )
        out["reasons"] = crossed(rules, streak=streak, gate=gate, failed_runs=failed)
    except Exception as exc:  # noqa: BLE001 - a check that cannot be done counts as crossed
        log.warning("brain.pause_rules.unreadable", error=str(exc))
        out["reasons"] = ["The pause rules could not be checked, so the brain is put back in practice to be safe."]
    return out


def apply(db: Session, rules: PauseRules | None = None, today: date | None = None) -> str | None:
    """Put the brain back in practice if a rule is crossed. Returns the Telegram text, or None."""
    from swing_trade_ml.services.brain_golive.stage import set_stage

    result = evaluate(db, rules, today)
    if not result["reasons"]:
        return None
    reason = SEALED_REASON if trial_seal.active() else " ".join(result["reasons"])
    set_stage(db, "shadow", by=PAUSE_BY, reason=reason)
    log.warning("brain.pause_rules.paused", previous=result["stage"], reasons=result["reasons"])
    return (
        "⏸️ <b>Brain paused: back in practice</b>\n"
        f"{reason}\n"
        "Nothing new will be bought for the brain. Stocks it already holds keep their normal stop, "
        "target and time-stop exits. You can move it out of practice again on the Go-live page."
    )
