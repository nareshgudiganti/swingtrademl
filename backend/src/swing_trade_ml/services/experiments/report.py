"""What the experiments show so far, per horizon, with sample size and uncertainty. Never a "validated" label:
the verdict is "Not proven" until the owner reviews it after the protocol's minimum sample and earliest
date."""

from __future__ import annotations

from datetime import date
from statistics import fmean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.experiments import ExperimentOutcome, ExperimentSelection

from . import rules
from .ledger import active_selections
from .protocol import PROTOCOL_V1, Protocol, ensure_owner_cohort, protocol_from_row

OWNER_SELECTED_NOTE = (
    "These picks were chosen by hand. Results describe this research experiment only; "
    "they do not show that any AI model works."
)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return fmean(xs) if xs else None


def build(db: Session, *, today: date, intended: int | None = None, protocol: Protocol = PROTOCOL_V1) -> dict:
    protocol_row, _ = ensure_owner_cohort(db, protocol)
    protocol = protocol_from_row(protocol_row)
    active = {s.id for s in active_selections(db)}  # picks replaced by a correction are not reported
    rows = db.execute(
        select(ExperimentOutcome, ExperimentSelection)
        .join(ExperimentSelection, ExperimentSelection.id == ExperimentOutcome.selection_id)
        .where(ExperimentOutcome.protocol_id == protocol_row.id)
    ).all()
    rows = [(o, s) for o, s in rows if s.id in active]
    if intended is not None:
        rows = [(o, s) for o, s in rows if s.intended_horizon == intended]
    horizons = []
    for h in protocol.horizons:
        mine = [(o, s) for o, s in rows if o.horizon == h]
        closed = [(o, s) for o, s in mine if o.state == "closed"]
        nets = [o.net_return for o, _ in closed]
        windows = [(s.entry_session, o.exit_session) for o, s in closed]
        # Independent samples = distinct entry dates (picks made the same day share one market). The stricter
        # count of non-overlapping holding windows is shown beside it.
        independent = len({s.entry_session for _, s in closed})
        enough = independent >= protocol.min_independent_samples and today >= date.fromisoformat(
            protocol.earliest_verdict
        )
        rng = rules.bootstrap_mean_range(nets)
        horizons.append(
            {
                "horizon": h,
                "label": protocol.label,
                "verdict": "Not proven" if not enough else "Ready for the owner's review (not a verdict)",
                "closed": len(closed),
                "open": sum(o.state == "open" for o, _ in mine),
                "pending": sum(o.state == "pending" for o, _ in mine),
                "data_issues": sum(o.state == "data_issue" for o, _ in mine),
                "void": sum(o.state == "void" for o, _ in mine),
                "independent_samples": independent,
                "independent_entry_dates": independent,
                "non_overlapping": rules.non_overlapping(windows),
                "minimum_needed": protocol.min_independent_samples,
                "period": {
                    "from": min((s.entry_session for _, s in closed), default=None),
                    "to": max((o.exit_session for o, _ in closed), default=None),
                },
                "mean_net_return": _mean(nets),
                "median_net_return": median(nets) if nets else None,
                "mean_net_return_per_day": _mean([n / h for n in nets]),
                "mean_excess_vs_nifty": _mean([o.excess_vs_nifty for o, _ in closed]),
                "mean_excess_vs_universe": _mean([o.excess_vs_universe for o, _ in closed]),
                "net_return_range_90": list(rng) if rng else None,
                "win_rate": (sum(n > 0 for n in nets) / len(nets)) if nets else None,
            }
        )
    rejected = db.scalars(select(ExperimentSelection).where(ExperimentSelection.status == "rejected")).all()
    return {
        "protocol": {"code": protocol.code, **protocol_row.params},
        "owner_selected_note": OWNER_SELECTED_NOTE,
        "intended_filter": intended,
        "horizons": horizons,
        "rejected_picks": len(rejected),
        "limits": [
            "Daily prices only: slippage is an assumption (0.10% a side), not a measured fill.",
            "Costs use the app's paper cost model as frozen on the protocol date.",
            "Prices are not adjusted for splits or bonuses; such windows are flagged and not scored.",
            "Picks whose holding periods overlap are not independent; see non_overlapping.",
            "Pick returns are after costs and slippage; NIFTY and the average stock are measured "
            "before costs, so the gaps shown are slightly harsh on the picks.",
            "Picks with a data issue (missing price, a one-day jump over 30%, a split or bonus) or that "
            "could not be simulated are left out of every average; the counts are shown. The jump rule "
            "also leaves out genuine crashes and spikes.",
            "Same-stock buy-and-hold is the same as the gross return under time-only exits, so it is "
            "not a separate benchmark here.",
            "The average stock leaves out stocks with missing prices, big jumps or a split/bonus in the "
            "window.",
        ],
    }
