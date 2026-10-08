"""Validation-phase evidence: a report on a replayed week, and two integrity checks.

Everything here only reads what the brain already stored (`brain_runs`,
`brain_decisions`) and what `replay_week` returned. It never changes a run, a
module mode or a decision, and it writes no database rows. The report is plain
data (`to_dict()` → JSON) so a week of evidence can be committed or diffed.

Nothing is invented: every sentence in the summary comes from a number or a
stored reason in the report.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import service
from swing_trade_ml.brain.module import REGISTRY
from swing_trade_ml.brain.replay_week import ReplayDayResult, format_counts
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun

SCHEMA_VERSION = 1

_ALL_WORDS = {w.value for w in c.IdeaWord} | {w.value for w in c.HoldingWord}


# --- the fingerprint -------------------------------------------------------


def decision_fingerprint(pairs: Iterable[tuple[str, str]], banner_mode: str | None) -> str:
    """sha256 of the sorted (symbol, word) pairs plus the banner mode.

    Only the words, never scores or prices: a score may drift in the last
    decimal, but a stock changing from WAIT to TRADE is what must be noticed.
    """
    body = json.dumps(
        {"banner": banner_mode, "decisions": sorted([s, w] for s, w in pairs)},
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# --- the report structure --------------------------------------------------


@dataclass
class ConstitutionChecks:
    """True means the stored run obeyed the rule. `problems` says why not."""

    vocabulary_valid: bool = True  # every word is one of the settled words
    every_stock_has_reason: bool = True  # C11
    every_stock_decided: bool = True  # C11: no stock in the run is missing
    no_trade_without_risk_gate: bool = True  # C1
    no_trade_when_banner_blocks: bool = True  # C2
    stale_data_never_trade: bool = True  # C5
    downgrades_have_reason: bool = True  # monotonic downgrades are explained
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class DayReport:
    day: str
    run_id: str
    banner: str
    universe_size: int
    counts: dict[str, int]
    fingerprint: str
    data_manifest: dict
    constitution: ConstitutionChecks


@dataclass
class ValidationReport:
    schema_version: int
    generated_at: str
    book: str
    start: str
    end: str
    days: list[DayReport]
    #: The /brain/compare snapshot (shadow ideas vs version 1), taken as given.
    compare: dict
    notes: list[str] = field(default_factory=list)

    @property
    def run_ids(self) -> list[str]:
        return [d.run_id for d in self.days]

    @property
    def constitution_ok(self) -> bool:
        return all(d.constitution.ok for d in self.days)

    def to_dict(self) -> dict:
        out = asdict(self)
        out["run_ids"] = self.run_ids
        out["constitution_ok"] = self.constitution_ok
        return out


# --- building it -----------------------------------------------------------


def constitution_checks(
    run: BrainRun, decisions: list[BrainDecision], universe_size: int
) -> ConstitutionChecks:
    """Re-check the safety rules on what was STORED (not on the live context)."""
    checks = ConstitutionChecks()
    trades = [d for d in decisions if d.word == c.IdeaWord.TRADE.value]

    def fail(flag: str, message: str) -> None:
        setattr(checks, flag, False)
        checks.problems.append(message)

    bad_words = sorted({d.word for d in decisions} - _ALL_WORDS)
    if bad_words:
        fail("vocabulary_valid", f"unknown decision word(s): {', '.join(bad_words)}")
    if any(not d.reasons for d in decisions):
        fail("every_stock_has_reason", "a decision was stored without a reason")
    if len({d.symbol for d in decisions}) < universe_size:
        fail(
            "every_stock_decided",
            f"{len({d.symbol for d in decisions})} stocks decided but the run covered {universe_size}",
        )

    mandatory = {cls.manifest.id for cls in REGISTRY.all() if cls.manifest.mandatory}
    gate_used = any(e.get("module_id") in mandatory and e.get("status") == "used" for e in run.trace or [])
    if trades and not gate_used:
        fail("no_trade_without_risk_gate", f"{len(trades)} TRADE word(s) but the risk gate did not run")
    if trades and run.banner_mode == c.MarketMode.NO_NEW_TRADES.value:
        fail("no_trade_when_banner_blocks", f"{len(trades)} TRADE word(s) under a NO_NEW_TRADES banner")

    quality = run.quality or {}
    stale = set(quality.get("stale") or [])
    stale_trades = sorted(d.symbol for d in trades if d.symbol in stale)
    if stale_trades:
        fail("stale_data_never_trade", f"TRADE on stale data: {', '.join(stale_trades)}")
    overall = quality.get("overall")
    if overall is not None and not overall.get("fresh", True) and trades:
        fail("stale_data_never_trade", "TRADE words although market-wide data was not fresh")

    if any(d.downgraded_from and not d.downgrade_reason for d in decisions):
        fail("downgrades_have_reason", "a decision was lowered without a stored reason")
    return checks


def build_day_report(db: Session, result: ReplayDayResult) -> DayReport:
    run = db.get(BrainRun, result.run_id)
    decisions = service.decisions_for(db, result.run_id)
    manifest = ((run.context or {}).get("data_manifest") or {}) if run else {}
    return DayReport(
        day=result.day.isoformat(),
        run_id=result.run_id,
        banner=result.banner,
        universe_size=result.universe_size,
        counts=dict(result.counts),
        fingerprint=decision_fingerprint([(d.symbol, d.word) for d in decisions], result.banner),
        data_manifest=manifest,
        constitution=constitution_checks(run, decisions, result.universe_size)
        if run
        else ConstitutionChecks(problems=["run row not found"]),
    )


def build_report(
    db: Session,
    results: list[ReplayDayResult],
    *,
    book: str,
    start: date,
    end: date,
    compare_snapshot: dict | None,
    now: datetime | None = None,
) -> ValidationReport:
    notes: list[str] = []
    compare = compare_snapshot or {}
    if not results:
        notes.append("No trading days fell in the range, so nothing was replayed.")
    if not compare:
        notes.append("No /brain/compare snapshot was supplied.")
    elif not compare.get("brain_finished"):
        notes.append("Zero finished brain ideas so far: the comparison with version 1 is empty, not bad.")
    return ValidationReport(
        schema_version=SCHEMA_VERSION,
        generated_at=(now or datetime.now(UTC)).isoformat(),
        book=book,
        start=start.isoformat(),
        end=end.isoformat(),
        days=[build_day_report(db, r) for r in results],
        compare=compare,
        notes=notes,
    )


# --- output ----------------------------------------------------------------


def default_report_path(report: ValidationReport, evidence_dir: Path) -> Path:
    return evidence_dir / f"validation_week_{report.start}_{report.end}.json"


def write_report(report: ValidationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str) + "\n", "utf-8")
    return path


def plain_summary(report: ValidationReport) -> str:
    """A few plain-English lines for the terminal."""
    lines = [
        f"Validation: {len(report.days)} trading day(s), {report.start} to {report.end} ({report.book})."
    ]
    total = Counter()
    for d in report.days:
        total.update(d.counts)
    if report.days:
        lines.append(f"Words given in total: {format_counts(dict(total))}.")
        blocked = sum(1 for d in report.days if d.banner == c.MarketMode.NO_NEW_TRADES.value)
        if blocked:
            lines.append(
                f"{blocked} day(s) said NO NEW TRADES. That is the brain being careful, not a fault."
            )
    if report.constitution_ok:
        lines.append("Safety rules: all held on every day.")
    else:
        lines.append("Safety rules: BROKEN on some day, look at these:")
        for d in report.days:
            lines += [f"  {d.day} {d.run_id}: {p}" for p in d.constitution.problems]
    lines += [f"Note: {n}" for n in report.notes]
    return "\n".join(lines)


# --- WHY integrity ---------------------------------------------------------


@dataclass
class WhyIntegrity:
    symbol: str
    ok: bool
    stored_run_id: str | None
    stored_word: str | None
    why_word: str | None
    problems: list[str]


def compare_why_to_stored(
    symbol: str, why: dict, stored: BrainDecision | None, stored_run_id: str | None
) -> WhyIntegrity:
    """Pure comparison of a /brain/why payload with a stored decision.

    Checks only facts: same word, and every trace entry names a real module id
    (or the runner's own "fallback"). It does not read or judge the narrative.
    """
    problems: list[str] = []
    why_decision = why.get("decision")
    why_word = why_decision.get("word") if why_decision else None
    if stored is None:
        problems.append("no stored nightly decision for this symbol")
    if why_decision is None:
        problems.append("the WHY answer has no decision for this symbol")
    if stored is not None and why_word is not None and why_word != stored.word:
        problems.append(f"WHY says {why_word} but the stored nightly decision is {stored.word}")
    trace = why.get("trace") or []
    if not trace:
        problems.append("the WHY answer has an empty trace")
    real_ids = {cls.manifest.id for cls in REGISTRY.all()} | {"fallback"}
    unknown = sorted({e.get("module_id") for e in trace} - real_ids)
    if unknown:
        problems.append(f"trace names module id(s) that do not exist: {', '.join(map(str, unknown))}")
    return WhyIntegrity(
        symbol=symbol.upper(),
        ok=not problems,
        stored_run_id=stored_run_id,
        stored_word=stored.word if stored else None,
        why_word=why_word,
        problems=problems,
    )


def latest_nightly(db: Session, book: str) -> BrainRun | None:
    return (
        db.query(BrainRun)
        .filter(BrainRun.kind == "nightly", BrainRun.book == book, BrainRun.status == "done")
        .order_by(BrainRun.as_of.desc(), BrainRun.started_at.desc())
        .first()
    )


def check_why_integrity(
    db: Session, symbol: str, *, book: str = "paper", why: dict | None = None
) -> WhyIntegrity:
    """Does asking WHY for `symbol` agree with the latest stored nightly decision?

    `why` is the /brain/why payload; when omitted it is produced the same way
    the endpoint does (a "why" run for that one stock), as of the nightly run's
    own moment so the two are comparable. That run is stored like any "why" run.
    """
    run = latest_nightly(db, book)
    stored = None
    if run is not None:
        stored = next((d for d in service.decisions_for(db, run.id) if d.symbol == symbol.upper()), None)
    if why is None:
        as_of = None if run is None or run.live else run.as_of
        _, why_run_id = service.run_brain(db, kind="why", as_of=as_of, symbols=[symbol], book=book)
        why_run = db.get(BrainRun, why_run_id)
        decision = next(
            (d for d in service.decisions_for(db, why_run_id) if d.symbol == symbol.upper()), None
        )
        why = {"decision": {"word": decision.word} if decision else None, "trace": why_run.trace}
    return compare_why_to_stored(symbol, why, stored, run.id if run else None)
