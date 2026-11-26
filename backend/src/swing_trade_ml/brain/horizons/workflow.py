"""One Brain workflow per horizon: pick the eligible model, apply that horizon's policy, record the result.

Pure: no database, no broker, no clock. A workflow never borrows another horizon's model. When nothing
is eligible it still records a result, "No decision for this horizon", with the reason.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite

from swing_trade_ml.brain.horizons.guard import horizon_refusal
from swing_trade_ml.brain.horizons.policy import DEFAULT_POLICIES, HORIZONS, HorizonPolicy
from swing_trade_ml.core import research_config

NO_DECISION = "NO_DECISION"
NO_DECISION_TEXT = "No decision for this horizon"


@dataclass(frozen=True, slots=True)
class ModelOutput:
    """One model's score for one stock, as handed to the Brain."""

    model_name: str
    model_version: str
    forecast_horizon_sessions: int  # what the model was trained to forecast
    role: str  # registry role: fold / final / prod / unmarked; each policy lists the roles it accepts
    symbol: str
    input_session: date  # the session whose data produced the score
    input_close: float
    score: float


@dataclass(frozen=True, slots=True)
class HorizonRecord:
    """What one workflow stores. Model, input session, horizon and due session always travel together."""

    decision_horizon: int
    symbol: str
    input_session: date
    evaluation_due_session: date | None
    decision: str  # TRADE / WATCH / WAIT, or NO_DECISION
    reason: str
    model_name: str | None = None
    model_version: str | None = None
    score: float | None = None
    input_close: float | None = None
    policy_code: str | None = None
    target_pct: float | None = None
    stop_pct: float | None = None
    half_out_pct: float | None = None


def due_session(sessions: Sequence[date], input_session: date, horizon: int) -> date | None:
    """The exchange session `horizon` sessions after the input session; None if the calendar is short."""
    i = bisect.bisect_left(sessions, input_session)
    if i == len(sessions) or sessions[i] != input_session or i + horizon >= len(sessions):
        return None
    return sessions[i + horizon]


def _refusal(out: ModelOutput, policy: HorizonPolicy, session: date) -> str | None:
    """Why this output cannot feed this horizon's decision, or None if it can."""
    label = f"{out.model_name} {out.model_version}"
    horizon = policy.horizon
    mismatch = horizon_refusal(label, out.forecast_horizon_sessions, horizon)
    if mismatch:
        return mismatch
    if out.role not in policy.eligible_roles:
        return f"{label} has role {out.role!r} and is not approved for decisions"
    if out.input_session != session:
        return f"{label} was scored on input session {out.input_session}, not {session}"
    if not isfinite(out.score) or not 0.0 <= out.score <= 1.0:
        return f"{label} has an unusable score {out.score!r}"
    if not isfinite(out.input_close) or out.input_close <= 0:
        return f"{label} has no usable input-session close"
    return None


def _decide(score: float, policy: HorizonPolicy) -> str:
    if score >= policy.trade_min_score:
        return "TRADE"
    if score >= policy.watch_min_score:
        return "WATCH"
    return "WAIT"


def run_horizon(
    horizon: int,
    outputs: Iterable[ModelOutput],
    session: date,
    sessions: Sequence[date],
    *,
    symbol: str | None = None,
    policies: Mapping[int, HorizonPolicy] = DEFAULT_POLICIES,
    research_caller: bool = False,
) -> HorizonRecord:
    """Run one horizon's workflow for one stock and session.

    `outputs` may hold models of any horizon; only a matching, approved model is used. When `symbol` is
    given it is the stock the record is stored under, and an output for any other stock is refused; without it
    the stock is taken from the outputs, and with neither it is an error (no made-up stock)."""
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {HORIZONS}")
    outputs = list(outputs)
    if symbol is None and outputs:
        symbol = outputs[0].symbol  # no stock was named, so the first output names it
    if symbol is None:
        raise ValueError("a symbol is required when there is no model output to take it from")
    due = due_session(sessions, session, horizon)

    def none(reason: str) -> HorizonRecord:
        return HorizonRecord(horizon, symbol, session, due, NO_DECISION, f"{NO_DECISION_TEXT}: {reason}")

    policy = policies.get(horizon)
    if policy is None or not policy.approved or policy.horizon != horizon:
        return none(f"the {horizon}-session decision policy is not approved")
    if not research_caller and research_config.is_research_only(horizon):
        # 10D and 15D are research-only (core/research_config.py): no decision word, except for research.
        return none(f"the {horizon}-session horizon is research-only")
    if due is None:
        return none(f"the exchange calendar does not reach {horizon} sessions after {session}")
    if not outputs:
        return none(f"no model output for {symbol} on {session}")
    if len({o.symbol for o in outputs}) > 1:
        return none("model outputs for more than one stock were given to one run")
    if outputs[0].symbol != symbol:  # the caller named the stock; an output for another one never decides it
        return none(f"the model output is for {outputs[0].symbol}, not {symbol}")

    refusals, eligible = [], []
    for out in outputs:
        reason = _refusal(out, policy, session)
        (refusals if reason else eligible).append(reason or out)
    if not eligible:
        return none("; ".join(refusals))
    if len(eligible) > 1:
        names = ", ".join(f"{o.model_name} {o.model_version}" for o in eligible)
        return none(f"more than one eligible {horizon}-session model ({names})")

    (model,) = eligible
    decision = _decide(model.score, policy)
    return HorizonRecord(
        decision_horizon=horizon,
        symbol=symbol,
        input_session=session,
        evaluation_due_session=due,
        decision=decision,
        reason=f"{model.model_name} {model.model_version} scored {model.score:.2f} under {policy.code}",
        model_name=model.model_name,
        model_version=model.model_version,
        score=model.score,
        input_close=model.input_close,
        policy_code=policy.code,
        target_pct=policy.target_pct,
        stop_pct=policy.stop_pct,
        half_out_pct=policy.half_out_pct,
    )


def run_all_horizons(
    session: date,
    outputs: Iterable[ModelOutput],
    sessions: Sequence[date],
    store,
    *,
    symbol: str,
    policies: Mapping[int, HorizonPolicy] = DEFAULT_POLICIES,
    research_caller: bool = False,
) -> dict[int, HorizonRecord]:
    """Run the 5D, 10D and 15D workflows independently for one stock and store all three results."""
    outputs = list(outputs)
    results = {}
    for horizon in HORIZONS:
        record = run_horizon(
            horizon,
            outputs,
            session,
            sessions,
            symbol=symbol,
            policies=policies,
            research_caller=research_caller,
        )
        store.add(record)
        results[horizon] = record
    return results
