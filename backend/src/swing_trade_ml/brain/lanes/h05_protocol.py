# backend/src/swing_trade_ml/brain/lanes/h05_protocol.py
# ruff: noqa: E501 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""h05: the 5-trading-day evaluation of the EXISTING production models (prod ids 2, 16, 17).

DRAFT protocol, revision 4 (2026-10-30). It is evaluation only: no retraining, no calibration, no activation,
no order. Every value below is part of `protocol_hash()`. A run refuses to start until the owner accepts the
protocol by putting that hash in LANE_H05_ACCEPTED_PROTOCOL_HASH. The U1-U4 values are PROPOSALS written down
so the hash can be accepted; accepting the hash is the owner's decision, not an assumption that it was made.

Costs are pinned here (not read from settings) so a later settings change cannot move a result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict

from swing_trade_ml.core.config import REPO_ROOT

PROTOCOL_CODE = "h05-protocol-v1-DRAFT-4"
PAGE_LABEL = "5 trading days · Existing model evaluation"
# What the scores ARE. Said on every report, because the lane does not replay what production served.
SCORING_LABEL = (
    "Existing model weights scored with training-compatible inputs. This is NOT an exact replay of what "
    "production served: production has served a different obv_slope formula since 2026-10-05, and its scores "
    "are kept only as a diagnostic."
)
EVIDENCE_DIR = "docs/brain/evidence/h05"

GROUPS = ("large", "mid", "small")

# What the owner's three production models must be. Checked against the registry row AND the artifact file.
# sha256 and n_features were read from the production backup (GET /ml/backup/models.zip) on 2026-10-30.
# Each model has its OWN input list (37 / 46 / 46 of today's 53), saved inside its artifact.
EXPECTED_MODELS = {
    "large": {
        "id": 2,
        "name": "swing_classifier",
        "version": "v2",
        "n_features": 37,
        "sha256": "d3a73b09a7b658e9a32c904e16ffd63de4ccdc9da824fbb09cc74370c8201f19",
    },
    "mid": {
        "id": 16,
        "name": "swing_classifier_midcap",
        "version": "v2",
        "n_features": 46,
        "sha256": "633259b084da1f3f0998c54795a03c8a641aca08e711ecf722021b3a21792a20",
    },
    "small": {
        "id": 17,
        "name": "swing_classifier_smallcap",
        "version": "v1",
        "n_features": 46,
        "sha256": "75675a4e465ca38d9e941e717db40703a6c097556a831e70b191c23a9dd2d358",
    },
}
# The question those models were trained on (prod: label_kind endpoint, 5 bars, +2%, no stop, uncalibrated).
LABEL_KIND = "endpoint"
HORIZON = 5
LABEL_TARGET = 0.02

# Feature definitions are frozen by the hash of the code that builds them (line endings normalised). The
# sealed-trial freeze already guards these files; the lane additionally stops if any of them differs.
FEATURE_CODE_SHA256 = {
    "ml/features.py": "96250895817d90cdbd19e1b3cda2dd5e1c89e96f508dd30aaac0d2f88c7286fe",
    "ml/market_context.py": "98c7e145636128fa61ee69f43f9abaad68b582da588593823722483479636ea0",
    "ml/sector_map.py": "8fb86130f49893770c4846bb4183f4c8369fd58f1c742f166c70dca27195f54a",
    "ml/predict.py": "4c1c53e8e2406dec3da697c1d467006794124a8a7a63b9e439910ce074113815",
}
# Which input values score a stock. The saved models expect obv_slope as it was when they were trained
# (OBV-level denominator, full history); production has used a different formula since 2026-10-05. The
# primary score is the one the saved models expect; the production-path score is stored as a diagnostic.
PRIMARY_BASIS = "training_basis"
DIAGNOSTIC_BASIS = "production_path"
# Feature parity (saved scaler vs today's code on the model's own training data), per input.
PARITY_MEAN_SHIFT_MAX = 0.25  # in the scaler's own standard deviations
PARITY_SD_RATIO_BAND = (0.75, 1.25)

# The fixed-rule shadow trade (a different question from the endpoint label above).
TRADE_TARGET = 0.02
TRADE_STOP = 0.04
TRADE_SESSIONS = 5
TOP_K = 5
DATA_READY_SHARE = 0.90  # the daily job records a session only once this share of the universe has its candle
JOB_CUTOFF_HOUR_IST = 9  # ... and gives up (the session is MISSED) at this hour on the next calendar day
ENTRY_OPEN_IST = (9, 15)  # the simulated entry fills at the open of session 1
MIN_BARS = 220  # the scorer's own requirement (ml/predict.py)
BIG_GAP = 0.20  # an overnight move beyond this inside a trade window is flagged, never removed
NOTIONAL_INR = 100_000.0

# Frozen costs. Brokerage is 0 (owner decision 17 Oct 2026: Zerodha delivery). Taxes and the depository fee are
# the code defaults of 2026-10-30, as in the horizon-v1 experiment ledger (services/experiments/protocol.py).
COSTS = {"brokerage_per_order": 0.0, "tax_bps_buy": 11.9, "tax_bps_sell": 10.4, "dp_charge_per_sell": 15.93}
# Slippage per side, by group. PROPOSED (U5) and an ASSUMPTION, not a measurement. Basis: a Corwin-Schultz
# high-low spread estimate computed from our own daily candles (last 250 sessions, 2026-10-30): median FULL
# spreads of about 24 / 36 / 51 bps for large / mid / small caps, i.e. roughly 12 / 18 / 25 bps per side. It
# is derived from candles alone: no quotes, no order book, no fills, no volume impact. The chosen values are
# rounded (large is slightly BELOW its estimate); the higher-cost sensitivity below is what tests them.
SLIPPAGE_BPS = {"large": 10.0, "mid": 20.0, "small": 25.0}
# Higher-cost sensitivity, reported next to every result (the ps3 cost-stress precedent): every fill 30 bps
# worse on top of the group slippage, and charges doubled.
STRESS = {"extra_slip_bps": 30.0, "charges_x": 2.0}
SLIPPAGE_STATUS = (
    "ASSUMPTION: slippage is derived from daily-candle high-low ranges, not from quotes, order books or fills. "
    "Real fills may be better or worse; the higher-cost sensitivity is reported next to every result."
)
# Every cost number and its unit, in one place (all are inputs to the hash).
COST_UNITS = {
    "slippage": "basis points of PRICE per side (1 bp = 0.01%), against us on both the entry and the exit",
    "taxes": "basis points of TURNOVER per order: buy 11.9, sell 10.4",
    "depository_charge": "rupees per SELL order, flat: Rs 15.93 (about 15.9 bps of a Rs 1,00,000 order; it does not scale with size)",
    "brokerage": "rupees per order: Rs 0 (delivery)",
    "notional": "Rs 1,00,000 per trade, whole shares; a price above that leaves the trade unresolved",
    "net_return": "a FRACTION of the cost basis after all of the above (0.01 = +1%), never a percentage-point figure",
    "round_trip_cost_bps_approx": {"large": 58, "mid": 78, "small": 88},
}

# Written-down rules (text is part of the hash, so changing a rule changes the hash).
RULES = {
    "signal": "close of the signal session; a stock is scored only if its last candle IS the signal session",
    "calendar": "market sessions = NIFTY 50 daily bars; session 1 is the first session after the signal",
    "entry": "open of session 1, buy slippage against us",
    "persist_before_entry": "a selection is written to the database before the open (09:15 IST) of session 1; from that moment the lane refuses to record that signal session (it is MISSED), so a delayed retry can never backdate an opening fill. Every row stores recorded_at; a trade whose row was recorded at or after its entry open is never simulated",
    "position_size": "every simulated trade, for picks AND baselines alike, buys floor(Rs 1,00,000 / entry fill) whole shares; return = (proceeds - cost) / cost where cost = shares x entry fill + buy charges, so rupee charges (depository Rs 15.93 per sell) become a percentage of the amount actually invested. A price above Rs 1,00,000 buys no share and is UNRESOLVED for picks and baselines alike",
    "collection_vs_finalisation": "collection of a run ends after its 60th signal session (status closed); finalisation waits until every selected AND baseline outcome of the run has matured (session 5 after the last signal day). Unresolved trades and not-evaluated labels are final states, not pending: they leave the daily series, are counted in the report, and never block finalisation or get replaced",
    "levels": "target +2% and stop -4% from the entry fill",
    "exit": "stop checked before target; a gap through a level fills at the open; else close of session 5",
    "same_candle": "a candle touching both levels counts as the STOP and is flagged ambiguous",
    "missing_candle": "a missing session candle inside the window leaves the trade UNRESOLVED (never guessed)",
    "corporate_actions": "prices are not adjusted; an overnight move beyond 20% in the window is flagged and reported with and without",
    "reference_prices": "endpoint label: signal close -> close of session 5. Shadow trade: executable entry fill -> target, stop or close of session 5. The two are never mixed",
    "maturity": "the label matures at the close of session 5 after the signal; the trade matures at its exit (target or stop on any of sessions 1-5, else the close of session 5). Session 6 is never read",
    "endpoint_label": "close of session 5 / signal close - 1 >= +2% (the training expression, on market sessions)",
    "eligibility": f"in the frozen group universe, unambiguous group, candle on the signal session, >= {MIN_BARS} bars, finite features",
    "no_filter_after_outcomes": "there is no liquidity or volatility filter, and none is added after outcomes are seen. Results are hypothetical fixed-rule selections, not evidence of executable portfolio returns",
    "feature_basis": "primary score = full-history features with obv_slope as the saved model was trained (OBV-level denominator); the production-path score is stored as a diagnostic and never selects",
    "scoring_label": SCORING_LABEL,
    "slippage_status": SLIPPAGE_STATUS,
    "cost_units": "see COST_UNITS: slippage in bps of price per side, taxes in bps of turnover, depository charge in rupees per sell order, net return as a fraction of cost basis",
    "missing_days": "a signal session inside a run window with no recorded day (job did not run, data not ready by the cut-off, or a lane stop) is MISSED: it is listed with its reason, never scored late, never replaced, and the run is NOT extended (run length counts sessions, not recorded days). A day with fewer than 10 eligible stocks in a group is recorded but is not evidence for that group. A day whose outcomes stay unresolved drops out of that group's daily series. Fewer than 40 matured days in a group makes that run INCONCLUSIVE for the group",
    "daily_job": "the job records a signal session only once its NIFTY bar exists and at least 90% of the universe has a candle on it; until 09:00 IST on the next calendar day it waits and retries; after that the session is missed. It never records a session twice and never starts a run",
    "ranking": "within the stock's own group only, score descending, ties by symbol ascending",
    "selection": f"top {TOP_K} per group per signal session (up to {TOP_K * 3} in total); shortfall recorded",
    "repeats": "a stock selected again within 4 sessions of a counted selection stays recorded but is not counted",
    "baselines": "every eligible stock in the group, and random 5 from the group (200 seeded draws), same days, fills, exits and costs",
    "uncertainty": "block bootstrap over signal days, blocks of 5, 90% range",
    "lane_stop": "if any frozen-model check fails for ANY group (model missing, changed, unreadable, or feature code changed) the WHOLE lane records nothing for that signal day, persists the reason as an event, and never substitutes another model. It resumes only when every identity equals the frozen one again; missed days are listed in the report",
    "frozen_across_runs": "model files, input lists, feature code, libraries, universe, execution and cost rules and this protocol are frozen across all three runs; daily market data advances normally and its provenance is recorded per day",
    "stress": "every trade is also scored with the higher-cost sensitivity; it never decides a verdict",
}

# PROPOSED values for U1-U4 (see the draft protocol for the justification). A run cannot start while any is None.
RUN_VALUES: dict[str, object] = {
    # U1: 60 consecutive signal sessions per run; run k+1 starts at the session after run k's last signal day.
    "run_length_sessions": 60,
    "run_boundaries": "consecutive, no gap and no overlap; a run ends on its 60th signal session",
    "outcome_maturity_sessions": 5,
    # U2
    "min_evidence_per_group": {
        "matured_signal_days": 40,
        "min_eligible_per_day": 10,
        "max_shortfall_day_share": 0.2,
    },
    # U3 (per group, per run): TWO verdicts, never merged.
    "verdict_rule": {
        "range_level": 0.90,
        "block_days": 5,
        "selection": "daily edge = counted picks' average net return minus the average net return of every eligible stock that day. PASS if the 90% block range is wholly above 0 (and the endpoint-label edge range is not wholly below 0); FAIL if wholly below 0; else INCONCLUSIVE. Beating a negative baseline is a selection result only",
        "economic": "daily series = the counted picks' own average net return (no baseline). PASS if the 90% block range is wholly above 0; FAIL if wholly below 0; else INCONCLUSIVE. A pick set that beats a losing baseline but loses money cannot pass",
        "no_merge": "there is no single combined go / no-go word; the report prints the pair and a one-sentence reading of it",
        "higher_cost": "reported next to both verdicts; it never decides one",
    },
    # U4 (per group, per verdict type, across the three runs). Selection and economic are combined separately.
    "combined_three_run_rule": {
        "pass": "at least 2 of 3 runs PASS, none FAIL, and the 90% block range of the pooled daily series (the three runs joined in order) is wholly above 0",
        "fail": "the pooled range is wholly below 0, or at least 2 runs FAIL",
        "otherwise": "INCONCLUSIVE",
        "min_runs_passing": 2,
        "groups": "each cap group is decided on its own; groups are never pooled",
    },
}

# Choices the owner confirms by accepting the hash (the draft default is what the code does today).
UNRESOLVED = [
    (
        "U1",
        "Run length 60 signal sessions; three runs back to back; an outcome matures at the close of session 5",
        "PROPOSED (power analysis in the protocol)",
    ),
    (
        "U2",
        "Minimum evidence per group per run: 40 matured signal days, 10+ eligible stocks a day, short top-5 on at most 20% of days",
        "PROPOSED",
    ),
    (
        "U3",
        "Two verdicts per group per run, never merged: SELECTION (picks vs the group's average stock) and ECONOMIC (picks' own net return after costs); 90% block range; INCONCLUSIVE is allowed",
        "PROPOSED",
    ),
    (
        "U4",
        "Three runs combine per group and per verdict type: >= 2 of 3 PASS, none FAIL, pooled range above 0",
        "PROPOSED",
    ),
    (
        "U5",
        "Slippage per side (bps of price): large 10 / mid 20 / small 25, plus the higher-cost sensitivity (+30 bps, charges x2). Derived from daily candles",
        "PROPOSED ASSUMPTION, not a measured fill",
    ),
    (
        "U6",
        "Levels measured from the entry fill or from the signal close (v1 uses the signal close)",
        "draft: entry fill",
    ),
    (
        "U7",
        "No liquidity or volatility filter, and none added after outcomes are seen (v1 has both)",
        "draft: none; volume is recorded",
    ),
    (
        "U8",
        "Repeat handling: headline counts a stock once per 5 sessions",
        "draft: count once, all selections reported too",
    ),
    ("U9", "Universe frozen for all three runs (draft) or refreshed per run", "draft: frozen"),
    (
        "U10",
        "Whether corporate-action-flagged trades stay in the headline",
        "draft: kept, reported with and without",
    ),
    (
        "U11",
        "Primary score uses the input formulas the saved models were trained on (obv_slope); the production-path score is a diagnostic",
        "PROPOSED (parity evidence in the protocol: the pre-change feature code reproduces the lane's inputs exactly)",
    ),
    (
        "U12",
        "Missed sessions are never made up and runs are not extended; fewer than 40 matured days makes a run INCONCLUSIVE for that group",
        "PROPOSED",
    ),
    (
        "U13",
        "Daily job records a session once >= 90% of the universe has its candle; waits until 09:00 IST next day; later the session is missed",
        "PROPOSED",
    ),
]

# The earlier 5-day test stays in the record. Source: docs/brain/evidence/fd_v1/ and the 26 Oct diagnostic review.
EARLIER_EVIDENCE = {
    "protocol": "fd-protocol-v1 (history, run once on 26 Oct 2026)",
    "result": "FAIL on both parts: skill 10 of 21 folds (lower bound -0.155%), money 3 of 17 folds (-0.42% per trade)",
    "note": "different design (fold models, v1 exits, 49 stocks); h05 does not replace or re-run it",
    "source": "docs/brain/evidence/fd_v1/five_day_2023-07-01_2025-01-31.md",
}

EXECUTION_NOTE = (
    "Hypothetical fixed-rule selections: no liquidity filter, no position limits, no money. "
    "These numbers are not evidence of executable portfolio returns."
)

VERSION_DIFFERENCES_FROM_V1 = [
    "v1 buys only when the score is at or above 0.60 (plus 0.10 when NIFTY is in a downtrend); h05 takes the top 5 per group whatever the score",
    "v1 exits early when the score falls to 0.35 or below, trails its stop and holds up to 30 calendar days; h05 has none of these",
    "v1 filters out stocks with a 20-day average volume under 100,000, daily volatility over 6% or a 5-day fall of 8%; h05 has no filter (U7)",
    "v1 needs 260 daily bars; h05 needs 220, the scorer's own minimum",
    "v1 sets its levels from the signal close; h05 from the entry fill (U6)",
    "v1 scores with the 400 newest bars and today's obv_slope formula; h05's primary score uses full history and the formula the models were trained on (U11)",
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
    feature_code: dict
    primary_basis: str
    parity: dict
    trade_target: float
    trade_stop: float
    trade_sessions: int
    top_k: int
    min_bars: int
    big_gap: float
    notional: float
    slippage_bps: dict
    stress: dict
    costs: dict
    rules: dict
    run_values: dict
    extras: dict


def frozen_params() -> FrozenParams:
    return FrozenParams(
        PROTOCOL_CODE,
        EXPECTED_MODELS,
        LABEL_KIND,
        HORIZON,
        LABEL_TARGET,
        FEATURE_CODE_SHA256,
        PRIMARY_BASIS,
        {"mean_shift_max": PARITY_MEAN_SHIFT_MAX, "sd_ratio_band": list(PARITY_SD_RATIO_BAND)},
        TRADE_TARGET,
        TRADE_STOP,
        TRADE_SESSIONS,
        TOP_K,
        MIN_BARS,
        BIG_GAP,
        NOTIONAL_INR,
        SLIPPAGE_BPS,
        STRESS,
        COSTS,
        RULES,
        RUN_VALUES,
        {
            "cost_units": COST_UNITS,
            "slippage_status": SLIPPAGE_STATUS,
            "scoring_label": SCORING_LABEL,
            "data_ready_share": DATA_READY_SHARE,
            "job_cutoff_hour_ist": JOB_CUTOFF_HOUR_IST,
        },
    )


def protocol_hash() -> str:
    from dataclasses import asdict

    blob = json.dumps(asdict(frozen_params()), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def missing_values() -> list[str]:
    return sorted(k for k, v in RUN_VALUES.items() if v is None)


class ProtocolError(RuntimeError):
    """The lane refuses: disabled, protocol not accepted or incomplete, or a model/identity mismatch."""


def accepted(settings: H05Settings | None = None) -> bool:
    s = settings or H05Settings()
    return bool(s.ACCEPTED_PROTOCOL_HASH) and protocol_hash() == s.ACCEPTED_PROTOCOL_HASH


def require_runnable(settings: H05Settings | None = None) -> None:
    """Every write path calls this first. Fails closed."""
    s = settings or H05Settings()
    if not s.ENABLED:
        raise ProtocolError("The h05 lane is disabled (LANE_H05_ENABLED is not true).")
    gaps = missing_values()
    if gaps:
        raise ProtocolError("The h05 protocol is incomplete; the owner has not set: " + ", ".join(gaps))
    if not accepted(s):
        raise ProtocolError(
            "The h05 protocol has not been accepted: LANE_H05_ACCEPTED_PROTOCOL_HASH does not match "
            "the current protocol hash."
        )
