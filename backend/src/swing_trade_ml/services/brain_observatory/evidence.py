"""Results kept apart by category for the monthly evidence pack (evidence plan task A3). Read-only.

Three categories, never added together, each read from the one place that already owns it:

| Category | What it is | Read from |
|---|---|---|
| backtest | frozen past-data test results | the reviewed verdict registry, judged by `verdicts.evaluate` |
| paper | the version 1 paper account | `services/portfolio.performance_stats` (as `/portfolio/summary`) |
| practice | brain ideas of the live nightly runs | `outcomes.build(..., "practice")` (Outcomes page) |

Every result is wrapped in an `Evidence` carrying its category. `require_one_category` refuses a mix, so a
caller cannot pool, say, backtest and practice numbers by accident. The category names are the same three
as `outcomes.CATEGORIES`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from swing_trade_ml.services.brain_observatory import defs


class Category(StrEnum):
    PRACTICE = "practice"
    BACKTEST = "backtest"
    PAPER = "paper"


CATEGORY_NAMES = {
    Category.BACKTEST: "Backtest (frozen tests on past data)",
    Category.PAPER: "Paper account (version 1, simulated money)",
    Category.PRACTICE: "Practice (brain ideas in the forward trial, nothing bought)",
}


class MixedCategoriesError(ValueError):
    """Raised when results from different categories would be combined."""


@dataclass(frozen=True, slots=True)
class Evidence:
    category: Category
    source: str  # the function or registry the numbers come from
    data: dict[str, Any]
    period: tuple[date, date] | None = None
    defs: str = field(default=defs.EVIDENCE_DEFS_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "category_name": CATEGORY_NAMES[self.category],
            "source": self.source,
            "period": None
            if self.period is None
            else [self.period[0].isoformat(), self.period[1].isoformat()],
            "defs": self.defs,
            "data": self.data,
        }


def require_one_category(items: Iterable[Evidence]) -> Category:
    """The single category shared by `items`; raises if there are none or more than one."""
    cats = {e.category for e in items}
    if len(cats) != 1:
        raise MixedCategoriesError(
            f"Evidence from different categories cannot be combined: {sorted(c.value for c in cats)}"
        )
    return cats.pop()


def practice(db, start: date, end: date) -> Evidence:
    """Brain ideas of the live nightly runs (paper book, practice stage) from `start` to `end`: exactly what
    the Observatory's Outcomes page shows for `category=practice`."""
    from swing_trade_ml.services.brain_observatory import outcomes

    return Evidence(
        Category.PRACTICE,
        "services/brain_observatory/outcomes.build",
        outcomes.build(db, start, end, Category.PRACTICE.value),
        (start, end),
    )


def paper(db) -> Evidence:
    """The paper account's headline figures for the current trial window, exactly as `/portfolio/summary`
    reports them (`mode=paper`, all books, not all-time)."""
    from swing_trade_ml.core.enums import TradingMode
    from swing_trade_ml.services.portfolio import performance_stats

    stats = performance_stats(db, TradingMode.PAPER)
    return Evidence(Category.PAPER, "services/portfolio.performance_stats", stats)


def backtest() -> Evidence:
    """The frozen test verdicts: the reviewed registry, judged by the Observatory's own verdict code (the
    same answers as `/brain/observatory/effectiveness`). Never recomputed, never edited."""
    from swing_trade_ml.services.brain_observatory import verdicts

    registry = verdicts.load_registry()
    return Evidence(
        Category.BACKTEST,
        "services/brain_observatory/verdicts.evaluate(validation_verdicts.REGISTRY)",
        {"claims": verdicts.evaluate(registry), "rejected_entries": verdicts.rejected_entries(registry)},
    )
