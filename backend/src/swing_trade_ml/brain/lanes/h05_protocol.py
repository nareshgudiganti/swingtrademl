# backend/src/swing_trade_ml/brain/lanes/h05_protocol.py
"""h05: the 5-trading-day evaluation of the EXISTING production models (prod ids 2, 16, 17).

DRAFT protocol. It is evaluation only: no retraining, no calibration, no activation, no order. Every value
below is part of `protocol_hash()`. A run refuses to start until the owner accepts the protocol by putting
that hash in LANE_H05_ACCEPTED_PROTOCOL_HASH, and refuses while any "unresolved" value is still None.

Costs are pinned here (not read from settings) so a later settings change cannot move a result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict

from swing_trade_ml.core.config import REPO_ROOT

PROTOCOL_CODE = "h05-protocol-v1-DRAFT"
PAGE_LABEL = "5 trading days · Existing model evaluation"
EVIDENCE_DIR = "docs/brain/evidence/h05"

GROUPS = ("large", "mid", "small")

# What the owner's three production models must be. Checked against the registry row AND the artifact.
EXPECTED_MODELS = {
    "large": {"id": 2, "name": "swing_classifier", "version": "v2"},
    "mid": {"id": 16, "name": "swing_classifier_midcap", "version": "v2"},
    "small": {"id": 17, "name": "swing_classifier_smallcap", "version": "v1"},
}
# The question those models were trained on (prod: label_kind endpoint, 5 bars, +2%, no stop, uncalibrated).
LABEL_KIND = "endpoint"
HORIZON = 5
LABEL_TARGET = 0.02

# The fixed-rule shadow trade (a different question from the endpoint label above).
TRADE_TARGET = 0.02
TRADE_STOP = 0.04
TRADE_SESSIONS = 5
TOP_K = 5
MIN_BARS = 220  # the scorer's own requirement (ml/predict.py)
BIG_GAP = 0.20  # an overnight move beyond this inside a trade window is flagged, never removed
NOTIONAL_INR = 100_000.0

# Frozen costs, copied from the code defaults of 2026-10-30. Brokerage is 0 (owner decision 17 Oct 2026:
# Zerodha delivery). Same values as the horizon-v1 experiment ledger (services/experiments/protocol.py).
SLIPPAGE_BPS = {"large": 10.0, "mid": 10.0, "small": 10.0}  # per side; group-specific values: see UNRESOLVED
COSTS = {"brokerage_per_order": 0.0, "tax_bps_buy": 11.9, "tax_bps_sell": 10.4, "dp_charge_per_sell": 15.93}

# Written-down rules (text is part of the hash, so changing a rule changes the hash).
RULES = {
    "signal": "close of the signal session; a stock is scored only if its last candle IS the signal session",
    "calendar": "market sessions = NIFTY 50 daily bars; session 1 is the first session after the signal",
    "entry": "open of session 1, buy slippage against us",
    "levels": "target +2% and stop -4% from the entry fill",
    "exit": "stop checked before target; a gap through a level fills at the open; else close of session 5",
    "same_candle": "a candle touching both levels counts as the STOP and is flagged ambiguous",
    "missing_candle": "a missing session candle inside the window leaves the trade UNRESOLVED (never guessed)",
    "corporate_actions": "prices are not adjusted; an overnight move beyond 20% in the window is flagged and "
    "reported with and without",
    "endpoint_label": "close of session 5 / signal close - 1 >= +2% (the training expression, on market sessions)",
    "eligibility": "in the frozen group universe, unambiguous group, candle on the signal session, "
    f">= {MIN_BARS} bars, finite features",
    "ranking": "within the stock's own group only, score descending, ties by symbol ascending",
    "selection": f"top {TOP_K} per group per signal session (up to {TOP_K * 3} in total); shortfall recorded",
    "repeats": "a stock selected again within 4 sessions of a counted selection stays recorded but is not counted",
    "baselines": "every eligible stock in the group, and random 5 from the group (200 seeded draws), "
    "same days, fills, exits and costs",
    "uncertainty": "block bootstrap over signal days, blocks of 5, 90% range",
}

# Left empty on purpose. The owner decides; a run cannot start while any of these is None.
UNRESOLVED_VALUES: dict[str, object] = {
    "run_length_sessions": None,
    "run_boundaries": None,
    "outcome_maturity_sessions": None,
    "min_evidence_per_group": None,
    "pass_fail_inconclusive_rule": None,
    "combined_three_run_rule": None,
}

# Choices the owner must still confirm (the draft default is what the code does today).
UNRESOLVED = [
    ("U1", "Run length, the three run boundaries and when an outcome counts as mature", "no default: owner decides"),
    ("U2", "Minimum evidence per group per run (signal days and finished trades)", "no default: owner decides"),
    ("U3", "PASS / FAIL / INCONCLUSIVE rule per group and per run", "no default: owner decides"),
    ("U4", "How three runs combine into one decision", "no default: owner decides"),
    ("U5", "Group-specific slippage and costs", "draft uses the same 10 bps per side for all three groups"),
    ("U6", "Levels measured from the entry fill or from the signal close (v1 uses the signal close)", "draft: entry fill"),
    ("U7", "Eligibility has no liquidity or volatility filter (v1 has both)", "draft: none; volume is recorded"),
    ("U8", "Repeat handling: headline counts a stock once per 5 sessions", "draft: count once, all selections reported too"),
    ("U9", "Universe frozen for all three runs (draft) or refreshed per run", "draft: frozen"),
    ("U10", "Whether corporate-action-flagged trades stay in the headline", "draft: kept, reported with and without"),
]

# The earlier 5-day test stays in the record. Source: docs/brain/evidence/fd_v1/ and the 26 Oct diagnostic review.
EARLIER_EVIDENCE = {
    "protocol": "fd-protocol-v1 (history, run once on 26 Oct 2026)",
    "result": "FAIL on both parts: skill 10 of 21 folds (lower bound -0.155%), money 3 of 17 folds (-0.42% per trade)",
    "note": "different design (fold models, v1 exits, 49 stocks); h05 does not replace or re-run it",
    "source": "docs/brain/evidence/fd_v1/five_day_2023-07-01_2025-01-31.md",
}

VERSION_DIFFERENCES_FROM_V1 = [
    "v1 buys only when the score is at or above 0.60 (0.70 in a NIFTY downtrend); h05 takes the top 5 per group whatever the score",
    "v1 exits early when the score falls to 0.35 or below, trails its stop and holds up to 30 calendar days; h05 has none of these",
    "v1 filters on volume, volatility and a falling-knife check; h05 has no filter (U7)",
    "v1 sets its levels from the signal close; h05 from the entry fill (U6)",
    "v1 trades one model per cap list with position slots and a money ceiling; h05 holds no slots and no money",
]


class H05Settings(BaseSettings):
    """Its own switches, so nothing about the lane lives in the shared Settings class."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_prefix="LANE_H05_",
        extra="ignore",
        case_sensitive=False,
    )

    ENABLED: bool = False
    ACCEPTED_PROTOCOL_HASH: str = ""


@dataclass(frozen=True)
class FrozenParams:
    code: str
    models: dict
    label_kind: str
    horizon: int
    label_target: float
    trade_target: float
    trade_stop: float
    trade_sessions: int
    top_k: int
    min_bars: int
    big_gap: float
    notional: float
    slippage_bps: dict
    costs: dict
    rules: dict
    unresolved: dict


def frozen_params() -> FrozenParams:
    return FrozenParams(
        PROTOCOL_CODE,
        EXPECTED_MODELS,
        LABEL_KIND,
        HORIZON,
        LABEL_TARGET,
        TRADE_TARGET,
        TRADE_STOP,
        TRADE_SESSIONS,
        TOP_K,
        MIN_BARS,
        BIG_GAP,
        NOTIONAL_INR,
        SLIPPAGE_BPS,
        COSTS,
        RULES,
        UNRESOLVED_VALUES,
    )


def protocol_hash() -> str:
    from dataclasses import asdict

    blob = json.dumps(asdict(frozen_params()), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def missing_values() -> list[str]:
    return sorted(k for k, v in UNRESOLVED_VALUES.items() if v is None)


class ProtocolError(RuntimeError):
    """The lane refuses: disabled, protocol not accepted or incomplete, or a model/identity mismatch."""


def require_runnable(settings: H05Settings | None = None) -> None:
    """Every write path calls this first. Fails closed."""
    s = settings or H05Settings()
    if not s.ENABLED:
        raise ProtocolError("The h05 lane is disabled (LANE_H05_ENABLED is not true).")
    gaps = missing_values()
    if gaps:
        raise ProtocolError("The h05 protocol is incomplete; the owner has not set: " + ", ".join(gaps))
    if s.ACCEPTED_PROTOCOL_HASH != protocol_hash():
        raise ProtocolError(
            "The h05 protocol has not been accepted: LANE_H05_ACCEPTED_PROTOCOL_HASH does not match "
            "the current protocol hash."
        )
