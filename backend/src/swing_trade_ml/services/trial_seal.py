"""The blind trial's seal: what may be SHOWN or SENT about the brain's live ideas while the trial runs.

Why: the forward trial (from TRIAL_START, 2026-10-14) is a blind test. If its results are looked at while
it runs, every later decision (keep going, change a rule, stop early) is made with the answer in view and
the trial stops being a clean test. Evidence plan amendment 1, section A4
(docs/superpowers/specs/2026-10-21-evidence-plan-amendment-1.md, branch docs/evidence-amendment-1),
approved by the owner on 2026-10-21 as a reporting-only change.

What "sealed" means: for the brain's live ideas decided on or after SEALED_FROM (brain decisions of live
runs, and version 1 Signal rows of the brain strategy), no outcome, return, hit rate, win rate, average,
edge, baseline comparison, best/worst move, or gate answer that reveals them (profit, beats random,
"pass", "behind") is returned or displayed. Counts stay (ideas, finished, still open, blocked, sessions,
"N of 30"). Safety and health information stays. Days before SEALED_FROM stay visible as before, and
version 1's own (non-brain) results stay visible.

What it does NOT change: trading, model scoring, M09 learning, the go-live gate's real decision
(services/brain_golive/stage.set_stage still works out profit and beating random internally), stored rows.
Only what endpoints, reports and command lines show.

Unsealing: set SEALED = False, only with the owner's approval, in its own recorded commit (and a row in
docs/brain/EXPOSURE-LEDGER.md). Every helper reads SEALED when it is called, so tests can switch it.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from swing_trade_ml.brain.trial_journal import GATE_MIN_IDEAS, MIN_SESSIONS, TRIAL_START

IST = ZoneInfo("Asia/Kolkata")
SEALED = True
SEALED_FROM: date = TRIAL_START
SEALED_TEXT = "Sealed until the trial's evaluation (blind test): counts only."
GATE_SEALED_TEXT = "The trial gate is not met yet (details sealed until the trial's evaluation)."

# The trial journal's per-set figures that are counts (kept); everything else in a set is a result.
COUNT_FIELDS = ("picked", "ideas", "still_open", "days", "edge_days", "finished", "open")


def active() -> bool:
    return bool(SEALED)


def sealed_from() -> date | None:
    """The first sealed day, or None when the seal is off."""
    return SEALED_FROM if SEALED else None


def is_sealed_day(d: date | None) -> bool:
    return bool(SEALED) and d is not None and d >= SEALED_FROM


def is_sealed_dt(dt: datetime | None) -> bool:
    """A timestamp's IST day is sealed (naive timestamps are read as UTC, as the database stores them)."""
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return is_sealed_day(dt.astimezone(IST).date())


def touches_seal(start: date | None, end: date | None) -> bool:
    """Does a date range (None = open-ended) include any sealed day?"""
    return bool(SEALED) and (end is None or end >= SEALED_FROM)


def counts_only(row: dict | None, keep: tuple[str, ...] = COUNT_FIELDS) -> dict | None:
    """The same keys, with every result set to None (the counts in `keep` stay)."""
    if row is None:
        return None
    return {k: (v if k in keep else None) for k, v in row.items()}


def sealed_gate(g: dict) -> dict:
    """The trial gate as it may be shown: counts and whether the counts are met, never profit, beating
    random, being clearly worse, or 'pass' / 'behind'. 'too early' is a count, so it stays."""
    if g.get("word") == "error":
        return {"word": "error", "error": g.get("error"), "sealed": True, "text": SEALED_TEXT}
    sessions, finished = int(g.get("sessions") or 0), int(g.get("finished") or 0)
    counts_met = sessions >= MIN_SESSIONS and finished >= GATE_MIN_IDEAS
    return {
        "sessions": sessions,
        "finished": finished,
        "sessions_needed": MIN_SESSIONS,
        "finished_needed": GATE_MIN_IDEAS,
        "counts_met": counts_met,
        "word": "sealed" if counts_met else "too early",
        "sealed": True,
        "text": SEALED_TEXT,
    }


def gate_counts_text(g: dict) -> str:
    return (
        f"{g.get('sessions', 0)} of {MIN_SESSIONS} trial sessions, {g.get('finished', 0)} of "
        f"{GATE_MIN_IDEAS} finished brain TRADE ideas since the trial started."
    )


# --- the trial journal ------------------------------------------------------------------------------


def seal_journal(j: dict) -> dict:
    """A trial journal as it may be shown. Summaries cover the whole range, so when any day of it is
    sealed they are counts only; days before the seal keep each pick's result, sealed days keep the
    symbols only. The gate is the sealed gate. Unchanged when the seal is off or no day is sealed."""
    last = j.get("last_day")
    if not SEALED or not last or date.fromisoformat(last) < SEALED_FROM:
        return j
    out = dict(j)
    out["summaries"] = {
        name: (counts_only(row) if isinstance(row, dict) else row) for name, row in j["summaries"].items()
    }
    days = []
    for d in j.get("days", []):
        if is_sealed_day(date.fromisoformat(d["day"])):
            picks = {name: [{"symbol": p["symbol"]} for p in rows] for name, rows in d["picks"].items()}
            d = {**d, "picks": picks, "sealed": True}
        days.append(d)
    out["days"] = days
    if "gate" in j:
        out["gate"] = sealed_gate(j["gate"])
    out["sealed"] = True
    out["sealed_from"] = SEALED_FROM.isoformat()
    out["sealed_text"] = SEALED_TEXT
    return out


def seal_daily_trial(trial: dict | None, day: date) -> dict | None:
    """A daily check's trial snapshot (stored or new) as it may be shown: counts only."""
    if not trial or not is_sealed_day(day):
        return trial
    out = dict(trial)
    gate = trial.get("gate")
    if isinstance(gate, dict) and gate.get("word") not in (None, "not started"):
        out["gate"] = sealed_gate({"sessions": trial.get("sessions"), **gate})
    if isinstance(trial.get("sets"), dict):
        out["sets"] = {
            k: {f: v.get(f) for f in ("picked", "ideas", "still_open")} if isinstance(v, dict) else v
            for k, v in trial["sets"].items()
        }
    if isinstance(trial.get("nifty"), dict):
        out["nifty"] = {k: trial["nifty"].get(k) for k in ("finished", "open")}
    out["sealed"] = True
    out["sealed_text"] = SEALED_TEXT
    return out


def journal_report_note() -> str:
    return (
        f"**{SEALED_TEXT}** From {SEALED_FROM.isoformat()} the forward trial is a blind test: only counts "
        "are shown until its evaluation. Days before it keep their results."
    )


def unsealed_warning() -> str:
    return (
        "WARNING: --unsealed shows the blind trial's results. Record this look in "
        "docs/brain/EXPOSURE-LEDGER.md (who, when, why) before reading on."
    )


# --- the learning report (M09 stays frozen; only what is shown is filtered) -------------------------


def learning_report(db, since: date | None = None) -> dict:
    """GET /brain/learning: M09's report with its breakdowns worked out from ideas decided before the
    seal only, by M09's own frozen functions. The trial's finished ideas are counted, never broken down.
    M09's scoring, learning and proposals are untouched (they still read every scored idea)."""
    from swing_trade_ml.brain.modules.m09_learn import learn, store
    from swing_trade_ml.brain.modules.m09_learn.failures import failure_patterns
    from swing_trade_ml.brain.modules.m09_learn.report import by_band, by_week, by_word, one_per_day

    if not SEALED:
        return learn.learning_report(db, since)
    rows = learn._scored_rows(db, since)
    mask = rows["decision_day"].map(is_sealed_day).astype(bool)
    shown, hidden = rows[~mask], rows[mask]
    n_shown, n_sealed = len(one_per_day(shown)), len(one_per_day(hidden))
    meta = {
        "n_scored_before_trial": n_shown,
        "n_scored_sealed": n_sealed,
        "sealed": True,
        "sealed_from": SEALED_FROM.isoformat(),
        "sealed_text": SEALED_TEXT,
    }
    if not n_sealed:  # nothing from the trial has finished: M09's own report shows nothing sealed
        return {**learn.learning_report(db, since), **meta}
    stored = store.latest_learning_run(db)
    if stored is None:
        drift, drift_lines, drift_note = [], [], learn.DRIFT_NEVER_CHECKED_NOTE
    else:
        drift, drift_lines, drift_note = stored.drift, stored.drift_lines, stored.drift_note
    notes = [
        f"{n_sealed} ideas decided since {SEALED_FROM.isoformat()} have finished. {SEALED_TEXT} "
        f"The figures below are only for ideas decided before then."
    ]
    if n_shown < learn.MIN_SCORED:
        notes.append(f"Only {n_shown} ideas from before the trial have finished: too few to judge.")
    return {
        "since": since,
        "n_scored": n_shown + n_sealed,
        **meta,
        "by_band": by_band(shown[shown["score_source"] == "model"]),
        "by_word": by_word(shown),
        "by_week": by_week(shown),
        "failures": failure_patterns(shown),
        "drift": drift,
        "drift_lines": drift_lines,
        "drift_note": drift_note,
        "note": " ".join(notes),
    }


def proposal_evidence(evidence: str | None, created_at: datetime | None) -> str | None:
    """A learning proposal made on or after the seal was worked out from the trial's results."""
    return SEALED_TEXT if is_sealed_dt(created_at) else evidence


# --- learning proposals (the stored rows and M09 stay as they are; only what is shown is sealed) -----

PROPOSAL_SEALED_TITLE = "A learning proposal was made (details sealed until the trial's evaluation)."
PROPOSAL_SEALED_NOTE = "Sealed during the blind trial"


def _owner_revert(kind: str | None, change: dict | None) -> bool:
    """The owner's own "go back to the default buy level" (m09_learn.store.revert_buy_level) is stored as
    a proposal, but it comes from the owner's click, never from the trial's results."""
    return kind == "buy_level" and isinstance(change, dict) and change == {"buy_level": None}


def proposal_sealed(kind: str | None, change: dict | None, created_at: datetime | None) -> bool:
    return is_sealed_dt(created_at) and not _owner_revert(kind, change)


def seal_proposal(out: dict, created_at: datetime | None) -> dict:
    """A learning proposal as it may be shown. One made on or after the seal was worked out from the
    trial's results, so its title ("Raise the buy level to 70%"), evidence and change (the new value, which
    says which way) would hint at them: they are replaced by sealed text. Its id, kind, status and dates
    stay, so the record of what happened to it is complete."""
    sealed = proposal_sealed(out.get("kind"), out.get("change"), created_at)
    if not sealed:
        return {**out, "sealed": False, "evidence_sealed": False}
    return {
        **out,
        "title": PROPOSAL_SEALED_TITLE,
        "evidence": SEALED_TEXT,
        "change": {},
        "sealed": True,
        "evidence_sealed": True,
        "sealed_note": PROPOSAL_SEALED_NOTE,
    }
