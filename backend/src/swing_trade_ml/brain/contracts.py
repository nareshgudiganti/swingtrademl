"""The data contracts brain modules exchange, and the decision vocabulary.

Modules talk to each other only through these shapes. Each record type has a
`CONTRACT` name with a major version ("Opinion@1"); a breaking change to a
shape bumps that version so a module built against the old one is refused at
start-up instead of misreading the new one.

The decision words are defined here and nowhere else. Their order matters:
every fallback and every safety check may only move a decision toward the
cautious end (see `downgrade`), which is what guarantees that a brain with
modules missing is more careful, never bolder.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar


class ContractError(ValueError):
    """A record or contribution does not match its declared contract."""


# --- vocabulary ------------------------------------------------------------


class IdeaWord(StrEnum):
    """For a stock the book does not own."""

    AVOID = "AVOID"
    WAIT = "WAIT"
    WATCH = "WATCH"
    TRADE = "TRADE"


class HoldingWord(StrEnum):
    """For a stock the book holds. There is no SELL: delivery trades only, so
    leaving a holding is EXIT."""

    EXIT = "EXIT"
    REDUCE = "REDUCE"
    MONITOR = "MONITOR"
    HOLD = "HOLD"


class MarketMode(StrEnum):
    NO_NEW_TRADES = "NO_NEW_TRADES"
    DEFENSIVE = "DEFENSIVE"
    NORMAL = "NORMAL"


# Most cautious first. The index is the rank.
_ORDER: dict[type[StrEnum], list[StrEnum]] = {
    IdeaWord: [IdeaWord.AVOID, IdeaWord.WAIT, IdeaWord.WATCH, IdeaWord.TRADE],
    HoldingWord: [HoldingWord.EXIT, HoldingWord.REDUCE, HoldingWord.MONITOR, HoldingWord.HOLD],
    MarketMode: [MarketMode.NO_NEW_TRADES, MarketMode.DEFENSIVE, MarketMode.NORMAL],
}


def rank(word: StrEnum) -> int:
    """0 = most cautious. Only comparable within one vocabulary."""
    return _ORDER[type(word)].index(word)


# --- records ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRequest:
    CONTRACT: ClassVar[str] = "RunRequest@1"
    run_id: str
    kind: str  # "nightly" | "intraday" | "why"
    as_of: datetime
    universe: tuple[str, ...]
    book: str = "paper"
    horizon_days: int = 15
    live: bool = True  # False for replays: live-only inputs (model, holdings) are skipped


@dataclass(frozen=True, slots=True)
class TraceEvent:
    CONTRACT: ClassVar[str] = "TraceEvent@1"
    step: str
    module_id: str  # "fallback" when the step's fallback answered
    status: str  # used | shadow | fallback | skipped | rejected
    reason: str = ""
    ms: int = 0
    version: str = ""


@dataclass(frozen=True, slots=True)
class DataQuality:
    CONTRACT: ClassVar[str] = "DataQuality@1"
    symbol: str  # "*" for the overall score
    score: float
    fresh: bool
    last_bar_date: str | None = None
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Snapshot:
    CONTRACT: ClassVar[str] = "Snapshot@1"
    symbol: str
    as_of: str  # date of the last bar used
    close: float
    atr_14: float | None = None
    adv_inr_20: float | None = None
    features: tuple[tuple[str, float], ...] = ()
    feature_set_version: str = ""


@dataclass(frozen=True, slots=True)
class MarketState:
    CONTRACT: ClassVar[str] = "MarketState@1"
    trend: str = "unknown"  # up | down | sideways | unknown
    volatility: str = "unknown"  # low | normal | elevated | unknown
    breadth_pct: float | None = None
    fii_net_5d_cr: float | None = None
    vix: float | None = None
    mode: MarketMode | None = None  # None = not decided yet; readers treat it as DEFENSIVE
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SectorState:
    CONTRACT: ClassVar[str] = "SectorState@1"
    sector: str
    rank: int
    of_total: int
    strength_20d: float | None = None
    rotation: str = "unknown"


@dataclass(frozen=True, slots=True)
class StockState:
    CONTRACT: ClassVar[str] = "StockState@1"
    symbol: str
    trend: str = "unknown"
    rel_strength_vs_nifty: float | None = None
    dist_from_52w_high_pct: float | None = None
    delivery_signal: str | None = None
    restrictions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Holding:
    symbol: str
    qty: int
    avg_price: float
    stop: float | None = None  # v1's active stop (it only ever moves up)
    target: float | None = None
    scaled_out: bool = False  # half already booked at the first target
    opened_on: date | None = None  # IST trading day of the entry (M15)


@dataclass(frozen=True, slots=True)
class PortfolioState:
    CONTRACT: ClassVar[str] = "PortfolioState@1"
    book: str
    value: float | None = None
    cash: float | None = None
    positions: tuple[Holding, ...] = ()
    drawdown_pct: float | None = None
    free_slots: int | None = None
    # M14: pairs (a, b, correlation) of stocks that moved closely together over
    # 60 days, and the largest position and sector as shares of the portfolio.
    correlated: tuple[tuple[str, str, float], ...] = ()
    largest_position: tuple[str, float] | None = None
    top_sector: tuple[str, float] | None = None


@dataclass(frozen=True, slots=True)
class SystemState:
    CONTRACT: ClassVar[str] = "SystemState@1"
    entries_halted: bool = False
    halt_reason: str | None = None
    exits_disabled: bool = False
    broker_ok: bool | None = None


@dataclass(frozen=True, slots=True)
class Situation:
    CONTRACT: ClassVar[str] = "Situation@1"
    scope: str  # market | sector | stock
    subject: str
    label: str
    confidence: float
    is_unknown: bool = False
    suggest_defensive: bool = False
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Recall:
    CONTRACT: ClassVar[str] = "Recall@1"
    symbol: str
    n_similar: int
    hit_rate: float | None = None
    median_return: float | None = None
    p25: float | None = None
    p75: float | None = None
    median_days: float | None = None
    mean_return: float | None = None  # average exit: +8%, -4%, or the day-15 close
    # What the evidence says to expect: the overall average plus only the part
    # of the similar cases' difference that held up on unseen months (M05).
    honest_hit_rate: float | None = None
    honest_mean_return: float | None = None
    key: str = ""  # the situation key used, in words
    widened: tuple[str, ...] = ()  # key parts dropped to find enough cases
    typical_path: tuple[tuple[int, float, float, float], ...] = ()  # (day, p25, p50, p75) for M15


@dataclass(frozen=True, slots=True)
class TrackPoint:
    """One open trade today against the band of similar past trades (M15)."""

    CONTRACT: ClassVar[str] = "TrackPoint@1"
    symbol: str
    day_n: int  # trading days since entry (0 = bought today)
    ret: float  # since entry, at the latest close
    status: str  # on track | drift | breakdown | stop hit | past horizon | no data
    reason: str
    horizon: int = 15
    band_low: float | None = None  # the 25th-75th percentile of similar trades on this day
    band_mid: float | None = None
    band_high: float | None = None
    stop: float | None = None
    first_target_note: str = ""
    band: tuple[tuple[int, float, float, float], ...] = ()  # the whole path, for the chart


@dataclass(frozen=True, slots=True)
class Opinion:
    CONTRACT: ClassVar[str] = "Opinion@1"
    source: str
    symbol: str
    stance: float  # -1 .. +1
    confidence: float  # 0 .. 1
    reasons: tuple[str, ...]
    probability: float | None = None
    threshold: float | None = None
    horizon_days: int = 15
    # True only when `probability` is a measured chance (M06's calibrated
    # combiner), not a ranking score; `evidence` says how it was measured.
    calibrated: bool = False
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class RiskVerdict:
    CONTRACT: ClassVar[str] = "RiskVerdict@1"
    symbol: str
    allowed: bool
    max_qty: int = 0
    rule: str | None = None
    reason: str = ""
    amount_inr: float | None = None
    note: str = ""  # context for the card (e.g. judged after a correlated idea, M14)


Word = IdeaWord | HoldingWord


@dataclass(frozen=True, slots=True)
class Decision:
    CONTRACT: ClassVar[str] = "Decision@1"
    symbol: str
    kind: str  # idea | holding
    word: Word
    reasons: tuple[str, ...]
    entry_low: float | None = None
    entry_high: float | None = None
    target: float | None = None
    stop: float | None = None
    qty: int = 0
    horizon_days: int = 15
    confidence: float | None = None
    evidence_text: str = ""
    downgraded_from: Word | None = None
    downgrade_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Banner:
    CONTRACT: ClassVar[str] = "Banner@1"
    mode: MarketMode
    headline: str
    reasons: tuple[str, ...] = ()


def downgrade(decision: Decision, to: Word, reason: str) -> Decision:
    """Lower a decision to `to`, keeping the reason first. A no-op when `to`
    is not strictly more cautious — this function can never make a decision
    bolder, whatever the caller asks for."""
    if type(to) is not type(decision.word) or rank(to) >= rank(decision.word):
        return decision
    return replace(
        decision,
        word=to,
        reasons=(reason, *decision.reasons),
        downgraded_from=decision.downgraded_from or decision.word,
        downgrade_reason=reason,
        # An idea that is no longer a TRADE has nothing to buy; a holding keeps its shares.
        qty=0 if isinstance(to, IdeaWord) and to is not IdeaWord.TRADE else decision.qty,
    )


def validate_record(record: object) -> None:
    """Checks a single record beyond its type: the rules that keep decisions
    explainable and in one vocabulary."""
    if isinstance(record, Decision):
        expected = IdeaWord if record.kind == "idea" else HoldingWord if record.kind == "holding" else None
        if expected is None:
            raise ContractError(f"Decision kind must be idea or holding, got {record.kind!r}")
        if not isinstance(record.word, expected):
            raise ContractError(f"{record.word} is not a {record.kind} word")
        if not record.reasons or not all(r.strip() for r in record.reasons):
            raise ContractError(f"Decision for {record.symbol} has no plain-English reason")
    elif isinstance(record, Opinion):
        if not -1.0 <= record.stance <= 1.0 or not 0.0 <= record.confidence <= 1.0:
            raise ContractError(f"Opinion from {record.source} is out of range")
    elif isinstance(record, DataQuality):
        if not 0.0 <= record.score <= 1.0:
            raise ContractError(f"Quality score for {record.symbol} is out of range")


# --- contribution ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Contribution:
    """What one module (or one step fallback) adds to the context. The runner
    merges it; modules never change the context themselves."""

    quality: tuple[DataQuality, ...] = ()
    snapshots: tuple[Snapshot, ...] = ()
    market: MarketState | None = None
    sectors: tuple[SectorState, ...] = ()
    stocks: tuple[StockState, ...] = ()
    portfolio: PortfolioState | None = None
    system: SystemState | None = None
    situations: tuple[Situation, ...] = ()
    recalls: tuple[Recall, ...] = ()
    opinions: tuple[Opinion, ...] = ()
    verdicts: tuple[RiskVerdict, ...] = ()
    decisions: tuple[Decision, ...] = ()
    banner: Banner | None = None
    tracks: tuple[TrackPoint, ...] = ()

    def records(self) -> list[object]:
        out: list[object] = []
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            out.extend(value if isinstance(value, tuple) else (value,))
        return out

    def contract_names(self) -> set[str]:
        return {type(r).CONTRACT for r in self.records()}


def validate_contribution(contribution: Contribution, declared_writes: tuple[str, ...]) -> None:
    """Every record must be a declared contract and pass its own checks."""
    if not isinstance(contribution, Contribution):
        raise ContractError(f"expected a Contribution, got {type(contribution).__name__}")
    undeclared = contribution.contract_names() - set(declared_writes)
    if undeclared:
        raise ContractError(f"wrote undeclared contracts: {', '.join(sorted(undeclared))}")
    for record in contribution.records():
        validate_record(record)
