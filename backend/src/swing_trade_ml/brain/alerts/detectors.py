"""What is worth telling the owner after a run: things that changed since the
previous comparable run.

Same pattern as the decision rules: each detector is one function from
(current run, previous run) to alert items. Add one by appending a
`Detector`; switch one off by passing its id in `disabled`. Items carry a
`key` the service uses to tell each thing only once a day, and a
`priority` (lower is shown first) so a stop hit always leads.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from swing_trade_ml.brain.contracts import HoldingWord, rank
from swing_trade_ml.services.limits import format_inr

WORRIED = {HoldingWord.MONITOR, HoldingWord.REDUCE, HoldingWord.EXIT}
PRIORITY = {"EXIT": 0, "banner": 1, "REDUCE": 2, "TRADE": 3, "MONITOR": 4}
MODE_PLAIN = {"NORMAL": "NORMAL", "DEFENSIVE": "DEFENSIVE", "NO_NEW_TRADES": "NO NEW TRADES"}


@dataclass(frozen=True, slots=True)
class DecisionView:
    symbol: str
    kind: str  # idea | holding
    word: str
    reason: str
    qty: int = 0
    entry_low: float | None = None
    entry_high: float | None = None
    target: float | None = None
    stop: float | None = None
    overruled_word: str | None = None

    @property
    def effective(self) -> str:
        """The owner's overrule wins over the brain's word."""
        return self.overruled_word or self.word


@dataclass(frozen=True, slots=True)
class RunView:
    run_id: str
    started_at: datetime
    banner_mode: str | None
    banner_headline: str | None
    decisions: dict[str, DecisionView] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AlertItem:
    key: str
    kind: str  # banner | trade | holding | (anything a new detector adds)
    symbol: str | None
    text: str  # plain text; the composer escapes it
    priority: int = 5


@dataclass(frozen=True, slots=True)
class Detector:
    id: str
    name: str
    find: Callable[[RunView, RunView | None], list[AlertItem]]


def _market_mode(cur: RunView, prev: RunView | None) -> list[AlertItem]:
    if not cur.banner_mode or (prev is not None and prev.banner_mode == cur.banner_mode):
        return []
    plain = MODE_PLAIN.get(cur.banner_mode, cur.banner_mode)
    return [
        AlertItem(
            f"banner:{cur.banner_mode}",
            "banner",
            None,
            f"Market: {plain} — {cur.banner_headline or ''}".rstrip(" —"),
            PRIORITY["banner"],
        )
    ]


def _trade_text(d: DecisionView) -> str:
    parts = [f"{d.symbol}: TRADE"]
    if d.qty and d.entry_low is not None and d.entry_high is not None:
        parts.append(f"{d.qty} shares near {format_inr(d.entry_low)} to {format_inr(d.entry_high)}")
    if d.target is not None and d.stop is not None:
        parts.append(f"target {format_inr(d.target)}, stop {format_inr(d.stop)}")
    return " — ".join([parts[0], ", ".join(parts[1:])]) if len(parts) > 1 else f"{parts[0]} — {d.reason}"


def _new_trades(cur: RunView, prev: RunView | None) -> list[AlertItem]:
    items = []
    for d in cur.decisions.values():
        if d.kind != "idea" or d.effective != "TRADE":
            continue
        before = prev.decisions.get(d.symbol) if prev else None
        if before is None or before.effective != "TRADE":
            items.append(AlertItem(f"trade:{d.symbol}", "trade", d.symbol, _trade_text(d), PRIORITY["TRADE"]))
    return items


def _holdings_worse(cur: RunView, prev: RunView | None) -> list[AlertItem]:
    items = []
    for d in cur.decisions.values():
        if d.kind != "holding":
            continue
        word = HoldingWord(d.effective)
        if word not in WORRIED:
            continue
        before = prev.decisions.get(d.symbol) if prev else None
        if (
            before is not None
            and before.kind == "holding"
            and rank(word) >= rank(HoldingWord(before.effective))
        ):
            continue  # not worse than last time
        items.append(
            AlertItem(
                f"holding:{d.symbol}:{word.value}",
                "holding",
                d.symbol,
                f"{d.symbol}: {word.value} — {d.reason}",
                PRIORITY[word.value],
            )
        )
    return items


DETECTORS: list[Detector] = [
    Detector("market_mode", "Tell me when the market mode changes", _market_mode),
    Detector("new_trades", "Tell me about new TRADE ideas", _new_trades),
    Detector("holdings_worse", "Tell me when a holding needs more attention", _holdings_worse),
]


def detect(
    current: RunView,
    previous: RunView | None,
    detectors: list[Detector] = DETECTORS,
    disabled: frozenset[str] = frozenset(),
) -> list[AlertItem]:
    items: list[AlertItem] = []
    for detector in detectors:
        if detector.id not in disabled:
            items.extend(detector.find(current, previous))
    return sorted(items, key=lambda i: (i.priority, i.key))
