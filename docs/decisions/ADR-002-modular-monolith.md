# ADR-002: One modular monolith, with enforced module boundaries

- **Date**: 2026-11-22
- **Status**: Proposed. Steps 0-1 approved; Steps 2-3 and database changes await the owner.
- **Reference**: `docs/architecture/TARGET-ARCHITECTURE-PROPOSAL.md` sections 0, 5, 6, 9 (M1, M2)
- **Built on `main`** (checked 2026-11-26): the registry `core/modules.py:102` and its lifecycle tests (#291), the durable owner-only switch, and import-direction and router-protection tests `backend/tests/test_module_boundaries.py` (#413). The test asserts that `heartbeat` and `check_exits` stay scheduled when the brain module is switched off (`backend/tests/test_module_registry_enforcement.py:118`); it does not name `reconcile_orders` or `signal_scan`, which no module owns.

## Context

TradeMind is one FastAPI app with Postgres/TimescaleDB, Redis and APScheduler. Module boundaries exist only by
convention, and the audit found four places where `services` import from `api`. One owner and a few developers work
in the same repo, so shared files collide easily.

## Decision

1. Keep **one application** and evolve it in place. No microservices, no event bus, no rewrite, no separate "v2"
   codebase (this agrees with principle 1 in `CLAUDE.md`).
2. Declare every module in one registry, `core/modules.py` (id, state, packages, routes, jobs, capabilities,
   `depends_on`). A lifecycle test proves each optional module can be switched off with the suite still green
   and its own jobs unscheduled, and that the protected jobs (`check_exits`, `reconcile_orders`, `signal_scan`,
   `heartbeat`) are still scheduled. A module switch never removes a protected job.
3. Enforce the dependency directions with import tests:
   - `core` <- product modules <- `api`
   - `brain` modules read only through `DatedReader`
   - `services` never import `api`
   - product modules never import each other's internals (use core services or published functions)
   - adapters (broker, holdings, billing, notifier, feed) are reached only through their port
4. Protected code (risk, limits, exits, execution, trial freeze, paper-mode latches) is never admin-editable and
   changes only through code, a test and the owner's sign-off (`review-risk`).

## Consequences

- New work is additive: new modules, nullable columns, tests. Existing behaviour is preserved by snapshot tests.
- Parallel work needs the module registry first, so the core wave starts with two or three developers.
- A boundary violation fails CI instead of being found in review.
- Not built: a plugin framework, and splitting the scheduler into a separate worker (deferred until required).
