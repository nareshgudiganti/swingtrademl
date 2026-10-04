"""M14 · Portfolio brain (plug-in to the state step).

Looks at the book as a whole: which ideas and holdings have moved together
over the last 60 trading days, and how concentrated the portfolio is
(correlation.py). It fills those facts into the portfolio state and gives
each new idea a `portfolio` modifier — a small nudge down and a card line
when it moves closely with something you already hold, a small nudge up
when it would add variety. The risk gate uses the pairs to judge an idea
that moves with a stronger idea of the same run after the others. It never
decides on its own; the sector cap stays in the risk gate either way.
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m14_portfolio.correlation import close_pairs, concentration, correlations

DOUBLING_UP = -0.1
ADDS_VARIETY = 0.05
VARIETY_BELOW = 0.3


@register_module
class PortfolioBrain(BrainModule):
    manifest = Manifest(
        id="M14",
        name="Portfolio brain",
        step=Step.STATE,
        kind="plugin",
        version="1.0.0",
        reads=(),
        writes=("PortfolioState@1", "Opinion@1"),
        budget_s=15.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        if view.request.kind == "intraday":
            return c.Contribution()
        reader = view.reader
        held = [h.symbol for h in view.holdings]
        ideas = [s for s in view.request.universe if s not in set(held)]
        closes = {s: reader.dated_closes(s) for s in dict.fromkeys((*held, *ideas))}
        corr = correlations(closes)
        pairs = tuple(close_pairs(corr)) if not corr.empty else ()

        values = {
            h.symbol: h.qty * float(closes[h.symbol].iloc[-1]) for h in view.holdings if len(closes[h.symbol])
        }
        numbers = reader.portfolio_numbers(view.request.book) or {}
        conc = concentration(values, numbers.get("value"))
        portfolio = c.PortfolioState(
            book=view.request.book,
            correlated=pairs,
            largest_position=conc["largest_position"],
            top_sector=conc["top_sector"],
        )

        opinions = []
        for idea in ideas if held else []:
            if idea not in corr.columns:
                continue
            with_held = corr.loc[idea, [h for h in held if h in corr.columns]].dropna()
            if with_held.empty:
                continue
            partner, value = with_held.idxmax(), float(with_held.max())
            if value > 0.7:
                opinions.append(
                    c.Opinion(
                        source="portfolio",
                        symbol=idea,
                        stance=DOUBLING_UP,
                        confidence=0.3,
                        reasons=(
                            f"Moves closely with {partner}, which you already hold "
                            f"(60-day correlation {value:.2f}) — buying both is close to doubling "
                            "one position.",
                        ),
                    )
                )
            elif with_held.abs().max() < VARIETY_BELOW:
                opinions.append(
                    c.Opinion(
                        source="portfolio",
                        symbol=idea,
                        stance=ADDS_VARIETY,
                        confidence=0.3,
                        reasons=(
                            "Adds variety: over the last 60 days it moved differently from "
                            "everything you hold.",
                        ),
                    )
                )
        return c.Contribution(portfolio=portfolio, opinions=tuple(opinions))
