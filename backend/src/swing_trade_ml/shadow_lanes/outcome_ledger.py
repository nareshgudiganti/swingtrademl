# ruff: noqa: E501 (long plain-English sentences)
"""Forward outcome ledger for the 5-day lane (#263). Read only; no migration; writes nothing.

It is a VIEW over records the lane already freezes (`h05_signals`, `h05_group_days`, `h05_events`, protected by
append-only triggers) plus the NIFTY 50 candles the horizon report already shows. It adds no verdict, changes no
stored value and imports nothing from the brain, the money tables or the sealed trial. The lane's own report has
no result seal, so there is none to apply here; the view shows only fields that report and the horizon report
already show.

CONTRACT (read by the #322 reports; every return is a FRACTION, 0.012 means 1.2%).

Response:  {"note", "criteria", "rows", "totals", "events", "counts"}

`rows` - grain: ONE row per recorded pick (`kind="pick"`: a selected top-5 stock of one run, signal day and
group) and ONE row per missed signal session (`kind="session"`). A pick appears once, however often this is read
or the outcomes are matured. Fields (ROW_FIELDS):
  kind, run_no, signal_day (IST date, ISO), group (large|mid|small, None for a session row), symbol (None for a
  session row), model_id, model_version, score, rank (frozen when the pick was recorded), recorded_at,
  status (completed | immature | missing | blocked), reason (plain English; the stored note or event text),
  label_status, trade_status (the lane's own words), trade_flags (the lane's stored flags for the shadow trade,
  shown unchanged as a list, [] when there are none or no trade yet, None on a session row: recorded_late,
  possible_corporate_action, same_candle_both_levels, gap_fill, ...; they change no status, count or number),
  endpoint_return (close of session 5 over the signal close), gross_return (stored exit fill over entry fill,
  after slippage and before charges; the fills already carry the slippage), net_return (stored, after charges and
  slippage), benchmark_return (NIFTY 50, open of the entry session to close of the exit session, no costs; it
  follows the SHADOW TRADE: present whenever the trade is final and its window is known, whatever the pick's
  overall status), benchmark_reason (why benchmark_return is empty, in words that fit: blocked, trade not
  finished, trade could not be worked out, window unknown, NIFTY candles missing; None when it is present),
  excess_vs_benchmark (net_return minus benchmark_return), passed (from the FINAL LABEL alone, whatever the
  shadow trade did: True when the close of session 5 reached the +2% rule, False when it did not; None for a
  blocked pick and while the label is pending or could not be evaluated). So the ledger's pass counts equal the
  h05 report's endpoint counts and the weekly report's hit counts, except that a blocked pick is excluded here.

Status, first match wins: blocked = recorded but not counted (a repeat inside five sessions);
immature = the label or the trade still waits for session 5; missing = a final "not evaluated" or "unresolved"
(a candle was missing), or a session nobody recorded, with the stored reason; completed = both are final.

`totals` - grain: one entry per (run_no, signal_day, group), built from the UNION of the group-day records and
the pick rows (a recorded day with no pick row still appears): picks, completed, immature, missing, blocked,
recorded_selected (the group-day record's own count; None when no record exists), universe_n, scored_n,
not_scored_n, shortfall (from the record), not_scored_reasons ({stored reason: stocks}) and reconciles (the four
statuses add up to picks AND picks equals recorded_selected). Entries with group None count missed sessions.
`events` - lane failures that are neither picks nor missed sessions (a frozen-model check that stopped the
lane, a day whose data was not ready): run_no, signal_day, kind, detail (the stored text); never counted.
`counts` - the four statuses over all pick rows.

Snapshot: the runs, picks and not-scored rows, group-day records and events are read in ONE SQL statement, so
they come from one database snapshot. A recorded day committed while this runs is either all in or all out; it
cannot make a total read reconciles=false by being half-seen. The NIFTY candles are a separate read (they are not
part of any reconciliation). Nothing is written and no session setting is changed.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from swing_trade_ml.shadow_lanes.horizon_report import nifty_bars, window_return

STATUSES = ("completed", "immature", "missing", "blocked")

# Stated here so a reader sees the rule; a test pins every value to the lane's frozen protocol.
CRITERIA: dict[str, Any] = {
    "horizon_sessions": 5,
    "endpoint_target": 0.02,
    "endpoint": "Pass = the close 5 market sessions after the signal is at least 2% above the signal close.",
    "trade_target": 0.02,
    "trade_stop": 0.04,
    "trade": "Shadow trade: bought at the open of session 1, +2% target, -4% stop, sold at the close of session 5 otherwise; costs and slippage included in the net return.",
}

ROW_FIELDS = (
    "kind",
    "run_no",
    "signal_day",
    "group",
    "symbol",
    "model_id",
    "model_version",
    "score",
    "rank",
    "recorded_at",
    "status",
    "reason",
    "label_status",
    "trade_status",
    "trade_flags",
    "endpoint_return",
    "gross_return",
    "net_return",
    "benchmark_return",
    "benchmark_reason",
    "excess_vs_benchmark",
    "passed",
)

NOTE = (
    "Test records only: not trades and not advice. Every number comes from the lane's frozen records; nothing here "
    "is recalculated into a verdict. Returns are fractions (0.012 means 1.2%)."
)
BLOCKED_REASON = "Chosen again within five sessions of an earlier pick, so it is recorded but not counted."
PENDING_REASON = "Session 5 has not happened yet, so the result is not known."


FINAL_TRADE = ("target", "stop", "expiry")
_DATE_FIELDS = ("signal_day", "entry_day", "exit_day", "label_day5")

# ONE statement reads the runs, the picks and not-scored rows, the group-day records and the events, so they all
# come from the same database snapshot: a recorded day that is committed while this runs is either all in or
# all out, and can never show as a false reconciles=false. Read only; no session setting is changed.
_SNAPSHOT = """
WITH r AS (SELECT id, run_no FROM h05_runs{run_filter}),
 s AS (SELECT * FROM h05_signals
       WHERE run_id IN (SELECT id FROM r) AND (selected OR status = 'not_scored')),
 g AS (SELECT * FROM h05_group_days WHERE run_id IN (SELECT id FROM r)),
 e AS (SELECT * FROM h05_events WHERE run_id IN (SELECT id FROM r))
SELECT (SELECT coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb) FROM r) AS runs,
       (SELECT coalesce(jsonb_agg(to_jsonb(s)), '[]'::jsonb) FROM s) AS signals,
       (SELECT coalesce(jsonb_agg(to_jsonb(g)), '[]'::jsonb) FROM g) AS group_days,
       (SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.id), '[]'::jsonb) FROM e) AS events
"""


def _record(raw: dict[str, Any]) -> SimpleNamespace:
    """A stored row as a plain object: ISO dates back to dates, timestamps to aware UTC datetimes."""
    row = dict(raw)
    for name in _DATE_FIELDS:
        if row.get(name):
            row[name] = date.fromisoformat(row[name])
    for name in ("recorded_at",):
        if row.get(name):
            row[name] = datetime.fromisoformat(row[name]).astimezone(UTC)
    return SimpleNamespace(**row)


def _read_snapshot(db: Session, run_no: int | None) -> tuple[dict[int, int], list, list, list]:
    stmt = text(_SNAPSHOT.format(run_filter=" WHERE run_no = :run_no" if run_no is not None else ""))
    out = db.execute(stmt, {"run_no": run_no} if run_no is not None else {}).one()
    runs = {r["id"]: r["run_no"] for r in out.runs}
    return (
        runs,
        [_record(x) for x in out.signals],
        [_record(x) for x in out.group_days],
        [_record(x) for x in out.events],
    )


def _status(s: SimpleNamespace) -> tuple[str, str]:
    if s.repeat_blocked:
        return "blocked", BLOCKED_REASON
    if s.label_status == "pending" or s.trade_status == "pending":
        return "immature", PENDING_REASON
    notes: list[str] = []
    if s.label_status == "not_evaluated":
        notes.append(f"Close of session 5 not evaluated: {s.label_note or 'no reason stored'}")
    if s.trade_status == "unresolved":
        notes.append(f"Shadow trade unresolved: {s.trade_note or 'no reason stored'}")
    if notes:
        return "missing", "; ".join(notes) + "."
    hit = "reached" if s.label_hit == 1 else "did not reach"
    return "completed", f"Shadow trade ended '{s.trade_status}'; the close of session 5 {hit} the +2% rule."


def _benchmark(s: SimpleNamespace, bars: dict) -> tuple[float | None, str | None]:
    """NIFTY 50 over the shadow trade's own window (entry session open to exit session close), or None with the
    reason there is none. It follows the TRADE's state, not the pick's overall status, and a reason never says
    "waiting" about a pick that is not waiting."""
    if s.repeat_blocked:
        return None, "Not counted: this pick is a repeat inside five sessions of an earlier one."
    if s.trade_status == "pending":
        return None, "The shadow trade has not finished yet: session 5 has not happened."
    if s.trade_status not in FINAL_TRADE:
        return None, f"The shadow trade could not be worked out ({s.trade_note or 'no reason stored'}), so there is no window to compare."
    if not bars:
        return None, "NIFTY 50 candles are not stored here, so there is no index comparison."
    if s.entry_day is None or s.exit_day is None:
        return None, "The pick's entry or exit day is not recorded, so its window is not known."
    value = window_return(bars, s.entry_day, s.exit_day)
    if value is not None:
        return value, None
    missing = [d.isoformat() for d in (s.entry_day, s.exit_day) if d not in bars]
    return None, f"No NIFTY 50 candle stored for {' and '.join(missing) or 'the window'}."


def _passed(s: SimpleNamespace) -> bool | None:
    """The +2% rule on the close of session 5, from the final label alone (so it equals the h05 report's and the
    weekly report's counts). A blocked pick is never counted; a label that is not final is neither pass nor fail."""
    if s.repeat_blocked or s.label_status != "evaluated" or s.label_hit is None:
        return None
    return s.label_hit == 1


def _pick_row(s: SimpleNamespace, run_no: int, bars: dict) -> dict[str, Any]:
    status, reason = _status(s)
    gross = s.exit_fill / s.entry_fill - 1 if s.entry_fill and s.exit_fill else None
    endpoint = s.label_close5 / s.signal_close - 1 if s.label_close5 and s.signal_close else None
    bench, bench_reason = _benchmark(s, bars)
    return {
        "kind": "pick",
        "run_no": run_no,
        "signal_day": s.signal_day.isoformat(),
        "group": s.group,
        "symbol": s.symbol,
        "model_id": s.model_id,
        "model_version": s.model_version,
        "score": s.score,
        "rank": s.group_rank,
        "recorded_at": s.recorded_at.isoformat() if s.recorded_at else None,
        "status": status,
        "reason": reason,
        "label_status": s.label_status,
        "trade_status": s.trade_status,
        "trade_flags": list(s.trade_flags or []),
        "endpoint_return": endpoint,
        "gross_return": gross,
        "net_return": s.net_return,
        "benchmark_return": bench,
        "benchmark_reason": bench_reason,
        "excess_vs_benchmark": (s.net_return - bench) if bench is not None and s.net_return is not None else None,
        "passed": _passed(s),
    }


def _session_row(e: SimpleNamespace, run_no: int) -> dict[str, Any]:
    row = dict.fromkeys(ROW_FIELDS)
    row.update(
        kind="session",
        run_no=run_no,
        signal_day=e.signal_day.isoformat() if e.signal_day else None,
        status="missing",
        reason=e.detail,
    )
    return row


def build(db: Session, run_no: int | None = None) -> dict[str, Any]:
    """The ledger for every run (or one). Pure read: no write, no flush, deterministic order."""
    runs, signals, group_days, all_events = _read_snapshot(db, run_no)
    bars, _sessions = nifty_bars(db)

    picks = [s for s in signals if s.selected]
    rows = [_pick_row(s, runs[s.run_id], bars) for s in picks]
    rows += [_session_row(e, runs[e.run_id]) for e in all_events if e.kind == "missed_session"]
    rows.sort(
        key=lambda r: (r["run_no"], r["signal_day"] or "", r["group"] or "", r["kind"], r["rank"] or 0, r["symbol"] or "")
    )
    # Failures that are not picks and not missed sessions (a frozen-model check that stopped the lane, a day
    # whose data was not ready): shown with their stored text, never counted anywhere.
    events = [
        {
            "run_no": runs[e.run_id],
            "signal_day": e.signal_day.isoformat() if e.signal_day else None,
            "kind": e.kind,
            "detail": e.detail,
        }
        for e in all_events
        if e.kind != "missed_session"
    ]

    # Totals start from the union of the group-day records and the pick rows, so a recorded day with no pick
    # row (none chosen, or lost) is still a line, and a pick with no record is one too.
    records = {(runs[g.run_id], g.signal_day.isoformat(), g.group): g for g in group_days}
    not_scored: dict[tuple, Counter] = {}
    for s in signals:
        if s.status != "not_scored":
            continue
        key = (runs[s.run_id], s.signal_day.isoformat(), s.group)
        not_scored.setdefault(key, Counter())[s.not_scored_reason or "no reason stored"] += 1
    per: dict[tuple, Counter] = {key: Counter() for key in records}
    for r in rows:
        c = per.setdefault((r["run_no"], r["signal_day"], r["group"]), Counter())
        if r["kind"] == "pick":
            c["picks"] += 1
            c[r["status"]] += 1
        else:
            c["missed_session"] += 1
    totals = []
    for key, c in sorted(per.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2] or "")):
        rno, day, group = key
        gd = records.get(key)
        entry = {
            "run_no": rno,
            "signal_day": day,
            "group": group,
            "picks": c["picks"],
            **{s: c[s] for s in STATUSES},
            "missed_sessions": c["missed_session"],
            "recorded_selected": gd.selected_n if gd else None,
            "universe_n": gd.universe_n if gd else None,
            "scored_n": gd.scored_n if gd else None,
            "not_scored_n": gd.not_scored_n if gd else None,
            "shortfall": gd.shortfall if gd else None,
            "not_scored_reasons": dict(not_scored.get(key, {})),
        }
        entry["reconciles"] = sum(entry[s] for s in STATUSES) == entry["picks"] and (
            group is None or entry["recorded_selected"] == entry["picks"]
        )
        totals.append(entry)
    counts = Counter(r["status"] for r in rows if r["kind"] == "pick")
    return {
        "note": NOTE,
        "criteria": CRITERIA,
        "rows": rows,
        "totals": totals,
        "events": events,
        "counts": {s: counts[s] for s in STATUSES},
    }
