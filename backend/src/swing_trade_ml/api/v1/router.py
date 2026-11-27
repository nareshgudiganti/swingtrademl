"""Aggregates every v1 endpoint module into one router."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from swing_trade_ml.api.deps import require_auth
from swing_trade_ml.api.module_capability import require_module_capability
from swing_trade_ml.api.v1.endpoints import (
    account_auth,
    account_deletion,
    admin_console,
    admin_modules,
    auth,
    backtest,
    beginner,
    billing,
    brain,
    brain_changes,
    brain_golive,
    brain_idea_report,
    brain_observatory,
    brain_shadow,
    company,
    compare,
    experiments,
    finance,
    groww,
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
    ops,
    orders,
    plans,
    portfolio,
    real_report,
    risk,
    safety,
    server_watch,
    service_keys,
    signals,
    strategies,
    system,
    weekly_report,
)
from swing_trade_ml.core.modules import require_module

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
api_router.include_router(service_keys.admin)
api_router.include_router(admin_modules.admin)
# Pro billing: 404 unless BILLING_ENABLED; each route checks its own caller (see endpoints/billing.py).
api_router.include_router(billing.router)
api_router.include_router(billing.admin)
# Account deletion: request/confirm/status/export 404 unless ACCOUNT_DELETION_ENABLED; cancel always works.
api_router.include_router(account_deletion.router)
# Admin console: owner-role person + two-step code; anyone else gets 404 (endpoints/admin_console.py).
api_router.include_router(admin_console.mfa_router)
api_router.include_router(admin_console.console)

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


def optional(module_id: str) -> list:
    """`protected`, then the module registry's guard (core/modules.py): sign-in is checked first, then, only
    while the module is switched off, its routes answer "switched off". Switched on (the default) nothing
    changes."""
    return [*protected, Depends(require_module(module_id)), Depends(require_module_capability(module_id))]


api_router.include_router(finance.router, dependencies=optional("finance"))
api_router.include_router(mutual_funds.router, dependencies=optional("mutual_funds"))
api_router.include_router(safety.router, dependencies=protected)
api_router.include_router(risk.router, dependencies=protected)
api_router.include_router(brain.router, dependencies=optional("brain"))
api_router.include_router(brain_changes.router, dependencies=optional("brain"))
api_router.include_router(brain_golive.router, dependencies=optional("brain"))
api_router.include_router(brain_idea_report.router, dependencies=optional("brain"))
api_router.include_router(brain_observatory.router, dependencies=optional("brain"))
api_router.include_router(brain_shadow.router, dependencies=optional("brain"))
api_router.include_router(experiments.router, dependencies=protected)
api_router.include_router(h05.router, dependencies=optional("research_lanes"))
api_router.include_router(weekly_report.router, dependencies=protected)
api_router.include_router(model_registry.router, dependencies=protected)
api_router.include_router(lane_picks.router, dependencies=optional("research_lanes"))
api_router.include_router(lanes.router, dependencies=optional("research_lanes"))
api_router.include_router(jobs.router, dependencies=protected)
# Read-only daily digest: owner or a read_ops / read_all service key only (endpoints/ops.py).
api_router.include_router(ops.router, dependencies=protected)
api_router.include_router(server_watch.router, dependencies=protected)
api_router.include_router(beginner.router, dependencies=protected)
# Each person's own watchlist: require_auth opens these few routes to every signed-in person
# (deps.SELF_SERVICE_ROUTES); the handlers only touch the caller's own rows.
api_router.include_router(my_watchlist.router, dependencies=protected)
# Groww holdings sync: owner only (each route also requires require_real_account), display only.
api_router.include_router(groww.router, dependencies=protected)
