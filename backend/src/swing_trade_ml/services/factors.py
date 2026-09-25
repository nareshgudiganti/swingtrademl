"""Factor scoring: ranking stocks against each other, one day at a time.

A factor is a *cross-sectional* percentile rank — every stock scored against
the others in that day's universe, never against an absolute threshold. That
is what keeps a score meaningful when the whole market moves together: in a
falling market the best-trending stock still ranks 100, because the question
is which stock to prefer, not whether the market is good.

Scores are inputs to candidate *selection* (see the spec's algorithm), not to
the model. They are deliberately not appended to ml/features.py's
FEATURE_COLUMNS: adding feature families inside the model has been tried four
times — sector, breadth, VIX, delivery percentage — and moved nothing each
time. The leverage here is narrowing the pool the model starts from.
"""

from __future__ import annotations

import pandas as pd

#: factor -> ((feature column, direction), ...) where direction is +1 when a
#: higher raw value is better and -1 when lower is better.
FACTOR_INPUTS: dict[str, tuple[tuple[str, int], ...]] = {
    "trend": (
        ("sma_50_ratio", 1),
        ("sma_200_ratio", 1),
        ("sma_50_200_cross", 1),
        ("adx_14", 1),
        ("trend_strength", 1),
        ("relative_strength_20d", 1),
        ("return_20d", 1),
        ("return_120d", 1),
        ("return_250d", 1),
    ),
    "low_volatility": (
        ("volatility_20", -1),
        ("atr_14_pct", -1),
        ("volatility_percentile_rank", -1),
    ),
}

AVAILABLE_FACTORS: frozenset[str] = frozenset(FACTOR_INPUTS)

#: Shown in the UI, disabled, with the reason — never faked with placeholder
#: numbers. Value and Quality need company financials (an NSE XBRL project);
#: a continuous Size rank needs real market capitalisation, which we do not
#: have. Cap *tier* is a universe filter instead (services/market_feeds.py).
STUBBED_FACTORS: dict[str, str] = {
    "value": "Needs company financials (earnings, book value)",
    "quality": "Needs company financials (profitability, debt)",
    "size": "Needs market capitalisation; use the cap-tier filter instead",
}


def percentile_rank(series: pd.Series) -> pd.Series:
    """0-100 rank of each value against the others present.

    Ties share the average rank. A single-row universe ranks 100 rather than
    raising, and an all-identical universe returns one shared rank rather than
    NaN — both are real cases on a thin day.
    """
    return series.rank(pct=True, method="average") * 100.0


def factor_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """One 0-100 score per available factor, per row of `frame`.

    `frame` is one row per stock for a single day, indexed by symbol, holding
    whatever feature columns are available. Inputs missing from the frame are
    skipped, so a factor still scores on the inputs it does have.
    """
    scores: dict[str, pd.Series] = {}
    for factor, inputs in FACTOR_INPUTS.items():
        parts = [
            percentile_rank(frame[column] * direction)
            for column, direction in inputs
            if column in frame.columns
        ]
        if not parts:
            continue
        scores[factor] = pd.concat(parts, axis=1).mean(axis=1)
    return pd.DataFrame(scores, index=frame.index)


def composite_score(scores: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted blend of the factors actually present in `scores`.

    Weights are renormalised over the factors that survive, so disabling one
    redistributes its weight instead of dragging every composite toward zero.
    A configuration weighting only unavailable factors is a configuration
    error and raises rather than silently scoring everything the same.
    """
    usable = {f: float(w) for f, w in weights.items() if f in scores.columns and w > 0}
    total = sum(usable.values())
    if total <= 0:
        raise ValueError("Weights must enable at least one factor present in the scores")

    blended = sum(scores[factor] * weight for factor, weight in usable.items())
    return blended / total
