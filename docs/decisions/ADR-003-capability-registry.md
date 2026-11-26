# ADR-003: One capability registry for switches, plans and roles

- **Date**: 2026-11-22
- **Status**: Proposed. Steps 0-1 approved; Steps 2-3 and database changes await the owner.
- **Reference**: `docs/architecture/TARGET-ARCHITECTURE-PROPOSAL.md` section 7 (M3)
- **Built on `main`** (checked 2026-11-26): only the first slice of #335, `plan_may_use_module` in `core/capabilities.py:20`, which maps plans to optional modules. **Not built:** the registry itself, `require_capability`, `/me/capabilities`, overrides and admin plan maps. The file name `core/capabilities.py` is already used, so the registry needs another name or the function moves; the lead decides.

## Context

Features are switched on and off by five separate mechanisms today (plan FEATURES, `ROUTE_RULES`, release switches,
environment flags, role checks). Nobody can answer "how is this feature turned on" from one place.

## Decision

1. One registry in `core/capabilities.py`. Each capability has a stable ID (for example `discover.view`,
   `history.scores`, `reports.export`), its module, a default, a `protected` flag, the plans it may be offered on,
   and a description.
2. The value resolves in this order: code default, environment (deploy-level switch), admin override (global
   on/off), plan entitlement (Free/Pro/future), role (owner, tester, member). The first two together are the
   **deployment layer**, and the environment value, when set, **replaces** the code default (the default is only
   the fallback). So an existing release switch that is off by default and that the deployment environment can
   enable (for example `ALLOW_MODEL_PROMOTION`) behaves exactly as it does today: off until the environment
   turns it on. **From the deployment layer onward a denial is final:** a capability is allowed only if the
   deployment layer allows it and every later layer allows it. An admin override, a plan or a role can narrow
   what the layer before it allows, never widen what the deployment layer denies. So a switch that the
   environment leaves off (or sets off, for example `ALLOW_MODEL_PROMOTION=false`) stays off whatever an
   admin override, plan or role says, and a `protected` capability cannot be turned on by an override at
   all. A snapshot test keeps each existing switch's behaviour (default off, enabled by the environment),
   and a test per switch proves that an override cannot re-enable a deployment denial.
3. The **backend enforces** with `require_capability("...")` on routes and in jobs. `/me/capabilities` returns the
   resolved map and the frontend only hides things.
4. The existing plan FEATURES, `ROUTE_RULES` and release switches are **migrated into the registry, not deleted**,
   and a per-route snapshot test proves current access is unchanged.
5. Three configuration tiers stay separate:
   - product config (module on/off, plan maps), changed by the owner in Admin with MFA step-up and an `audit_log`
     row per change;
   - research config (ADR-005), versioned;
   - protected safeguards (risk, sizing, exits, live-trading latches, freeze), never in Admin.

## Consequences

- A new feature is registered once (module + capability) and is switched on there. No deploy is needed to change a
  plan map.
- "Admin configures everything" is declined on purpose: safety and trading rules stay in code.
- Needs an admin screen for overrides and plan maps, with audit and revert.
