"""Aggregates every v1 endpoint module into one router."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from swing_trade_ml.api.deps import require_auth
from swing_trade_ml.api.v1.endpoints import (
    auth,
    backtest,
    brain,
    brain_golive,
    finance,
    instruments,
    market_data,
    ml,
    mutual_funds,
    notifications,
    orders,
    plans,
    portfolio,
    real_report,
    risk,
    safety,
    signals,
    strategies,
    system,
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
# /me/plan must answer every signed-in user whatever their plan (it is how
# the app learns what to show), and /admin/* checks for the owner itself.
api_router.include_router(plans.router)
api_router.include_router(plans.admin)

# Everything that can read positions or move money requires either a real
# dashboard login (JWT) or the shared X-API-Key (for scripts/automation),
# and — for anyone but the owner — a plan that includes that route.
protected = [Depends(require_auth)]
api_router.include_router(instruments.router, dependencies=protected)
api_router.include_router(market_data.router, dependencies=protected)
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
api_router.include_router(brain_golive.router, dependencies=protected)
