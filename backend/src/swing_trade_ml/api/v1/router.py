"""Aggregates every v1 endpoint module into one router."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from swing_trade_ml.api.deps import require_auth
from swing_trade_ml.api.v1.endpoints import (
    account_auth,
    auth,
    backtest,
    beginner,
    account_deletion,
    billing,
    brain,
    brain_changes,
    brain_golive,
    brain_observatory,
    brain_shadow,
    company,
    compare,
    experiments,
    finance,
    h05,
    instruments,
    invites,
    jobs,
    lane_picks,
    lanes,
    market_data,
    ml,
    model_registry,
    mutual_funds,
    my_watchlist,
    notifications,
    orders,
    plans,
    portfolio,
    real_report,
    release_switches,
    risk,
    safety,
    server_watch,
    signals,
    strategies,
    system,
    weekly_report,
)

api_router = APIRouter()

# Unauthenticated by design:
#  - system: health/readiness probes are called by the orchestrator, which
#    cannot carry credentials.
#  - auth: /auth/login has no credential yet by definition, and
#    /auth/kite/callback is loaded by Zerodha's redirect in a browser, which
#    cannot send custom headers.
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(account_auth.router)
api_router.include_router(account_auth.admin)
# Asking for an invite is public (rate-limited); /admin/invites/* checks for the signed-in owner itself.
api_router.include_router(invites.router)
api_router.include_router(invites.admin)
# /me/plan must answer every signed-in user whatever their plan (it is how
# the app learns what to show), and /admin/* checks for the owner itself.
api_router.include_router(plans.router)
api_router.include_router(plans.admin)
# Owner-only, read-only list of the release switches (checks require_owner itself).
api_router.include_router(release_switches.admin)
# Pro billing: 404 unless BILLING_ENABLED; each route checks its own caller (see endpoints/billing.py).
api_router.include_router(billing.router)
api_router.include_router(billing.admin)
# Account deletion: request/confirm/status/export 404 unless ACCOUNT_DELETION_ENABLED; cancel always works.
api_router.include_router(account_deletion.router)

# Everything that can read positions or move money requires either a real
# dashboard login (JWT) or the shared X-API-Key (for scripts/automation),
# and — for anyone but the owner — a plan that includes that route.
protected = [Depends(require_auth)]
api_router.include_router(instruments.router, dependencies=protected)
api_router.include_router(market_data.router, dependencies=protected)
api_router.include_router(company.router, dependencies=protected)
api_router.include_router(compare.router, dependencies=protected)
api_router.include_router(strategies.router, dependencies=protected)
api_router.include_router(signals.router, dependencies=protected)
api_router.include_router(orders.router, dependencies=protected)
api_router.include_router(portfolio.router, dependencies=protected)
api_router.include_router(real_report.router, dependencies=protected)
api_router.include_router(ml.router, dependencies=protected)
api_router.include_router(notifications.router, dependencies=protected)
api_router.include_router(backtest.router, dependencies=protected)
api_router.include_router(finance.router, dependencies=protected)
api_router.include_router(mutual_funds.router, dependencies=protected)
api_router.include_router(safety.router, dependencies=protected)
api_router.include_router(risk.router, dependencies=protected)
api_router.include_router(brain.router, dependencies=protected)
api_router.include_router(brain_changes.router, dependencies=protected)
api_router.include_router(brain_golive.router, dependencies=protected)
api_router.include_router(brain_observatory.router, dependencies=protected)
api_router.include_router(brain_shadow.router, dependencies=protected)
api_router.include_router(experiments.router, dependencies=protected)
api_router.include_router(h05.router, dependencies=protected)
api_router.include_router(weekly_report.router, dependencies=protected)
api_router.include_router(model_registry.router, dependencies=protected)
api_router.include_router(lane_picks.router, dependencies=protected)
api_router.include_router(lanes.router, dependencies=protected)
api_router.include_router(jobs.router, dependencies=protected)
api_router.include_router(server_watch.router, dependencies=protected)
api_router.include_router(beginner.router, dependencies=protected)
# Each person's own watchlist: require_auth opens these few routes to every signed-in person
# (deps.SELF_SERVICE_ROUTES); the handlers only touch the caller's own rows.
api_router.include_router(my_watchlist.router, dependencies=protected)
