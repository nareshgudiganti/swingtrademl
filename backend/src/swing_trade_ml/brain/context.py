"""The brain context: everything one run knows, filled in step by step.

Modules never touch it directly. They get a `ContextView` limited to the
contracts in their manifest's `reads`, and they return a Contribution that
`BrainContext.merge` folds in. Merge rules are first-writer-wins: a plug-in
that runs later can fill a gap an earlier module left, but never overwrite it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from types import MappingProxyType
from typing import Any

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import Manifest

# Contract name -> the context attribute that holds it.
CONTRACT_ATTR: dict[str, str] = {
    "DataQuality@1": "quality",
    "Snapshot@1": "snapshots",
    "MarketState@1": "market",
    "SectorState@1": "sectors",
    "StockState@1": "stocks",
    "PortfolioState@1": "portfolio",
    "SystemState@1": "system",
    "Situation@1": "situations",
    "Recall@1": "recalls",
    "Opinion@1": "opinions",
    "RiskVerdict@1": "verdicts",
    "Decision@1": "decisions",
    "Banner@1": "banner",
    "TrackPoint@1": "tracks",
}


def _fill_gaps(current: Any, new: Any) -> Any:
    """Keep `current`; take from `new` only the fields `current` left empty."""
    if current is None:
        return new
    if new is None:
        return current
    gaps = {
        f.name: getattr(new, f.name)
        for f in fields(current)
        if getattr(current, f.name) in (None, (), "unknown")
        and getattr(new, f.name) not in (None, (), "unknown")
    }
    return replace(current, **gaps) if gaps else current


@dataclass
class BrainContext:
    request: c.RunRequest
    reader: Any
    holdings: tuple[c.Holding, ...] = ()
    quality: dict[str, c.DataQuality] = field(default_factory=dict)
    snapshots: dict[str, c.Snapshot] = field(default_factory=dict)
    market: c.MarketState | None = None
    sectors: dict[str, c.SectorState] = field(default_factory=dict)
    stocks: dict[str, c.StockState] = field(default_factory=dict)
    portfolio: c.PortfolioState | None = None
    system: c.SystemState | None = None
    situations: list[c.Situation] = field(default_factory=list)
    recalls: dict[str, c.Recall] = field(default_factory=dict)
    opinions: list[c.Opinion] = field(default_factory=list)
    verdicts: dict[str, c.RiskVerdict] = field(default_factory=dict)
    decisions: dict[str, c.Decision] = field(default_factory=dict)
    banner: c.Banner | None = None
    tracks: dict[str, c.TrackPoint] = field(default_factory=dict)
    trace: list[c.TraceEvent] = field(default_factory=list)
    shadow: dict[str, c.Contribution] = field(default_factory=dict)
    risk_gate_ran: bool = False

    @classmethod
    def start(cls, request: c.RunRequest, reader: Any) -> BrainContext:
        holdings = tuple(reader.holdings(request.book)) if request.live else ()
        return cls(request=request, reader=reader, holdings=holdings)

    @property
    def held_symbols(self) -> tuple[str, ...]:
        return tuple(h.symbol for h in self.holdings)

    @property
    def idea_symbols(self) -> tuple[str, ...]:
        """New-idea candidates: the universe minus what the book already holds."""
        held = set(self.held_symbols)
        return tuple(s for s in self.request.universe if s not in held)

    @property
    def all_symbols(self) -> tuple[str, ...]:
        return (*self.idea_symbols, *self.held_symbols)

    def merge(self, contribution: c.Contribution) -> None:
        for q in contribution.quality:
            self.quality.setdefault(q.symbol, q)
        for s in contribution.snapshots:
            self.snapshots.setdefault(s.symbol, s)
        for s in contribution.sectors:
            self.sectors.setdefault(s.sector, s)
        for s in contribution.stocks:
            # The state engine's values are the floor; a plug-in only fills the
            # fields it left empty (e.g. M13's exchange restrictions).
            self.stocks[s.symbol] = _fill_gaps(self.stocks.get(s.symbol), s)
        for r in contribution.recalls:
            self.recalls.setdefault(r.symbol, r)
        for v in contribution.verdicts:
            self.verdicts.setdefault(v.symbol, v)
        for d in contribution.decisions:
            self.decisions.setdefault(d.symbol, d)
        for t in contribution.tracks:
            self.tracks.setdefault(t.symbol, t)
        self.situations.extend(contribution.situations)
        seen = {(o.source, o.symbol) for o in self.opinions}
        self.opinions.extend(o for o in contribution.opinions if (o.source, o.symbol) not in seen)
        self.market = _fill_gaps(self.market, contribution.market)
        self.portfolio = _fill_gaps(self.portfolio, contribution.portfolio)
        self.system = _fill_gaps(self.system, contribution.system)
        if self.banner is None:
            self.banner = contribution.banner

    def view_for(self, manifest: Manifest) -> ContextView:
        return ContextView(self, manifest)


class ContextView:
    """Read-only access to the contracts one module declared it reads."""

    __slots__ = ("_allowed", "_ctx", "_module_id")

    def __init__(self, ctx: BrainContext, manifest: Manifest) -> None:
        self._ctx = ctx
        self._module_id = manifest.id
        self._allowed = {CONTRACT_ATTR[name] for name in manifest.reads if name in CONTRACT_ATTR}

    @property
    def request(self) -> c.RunRequest:
        return self._ctx.request

    @property
    def reader(self) -> Any:
        return self._ctx.reader

    @property
    def holdings(self) -> tuple[c.Holding, ...]:
        return self._ctx.holdings

    def __getattr__(self, name: str) -> Any:
        if name not in CONTRACT_ATTR.values():
            raise AttributeError(name)
        if name not in self._allowed:
            raise c.ContractError(f"{self._module_id} read {name!r} without declaring it in reads")
        value = getattr(self._ctx, name)
        if isinstance(value, dict):
            return MappingProxyType(value)
        if isinstance(value, list):
            return tuple(value)
        return value
