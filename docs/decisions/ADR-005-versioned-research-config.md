# ADR-005: Trading-rule and research numbers live in one versioned place

- **Date**: 2026-11-22
- **Status**: Proposed. Steps 0-1 approved; Steps 2-3 and database changes await the owner.
- **Reference**: `docs/architecture/TARGET-ARCHITECTURE-PROPOSAL.md` sections 7 and 9 (M6, M7)
- **Built on `main`** (checked 2026-11-26): `core/research_config.py:75` (immutable versions, hash, `ACTIVE_VERSION`) and `GET /config/trading-rules` (`api/v1/endpoints/system.py:236`, #416). It is code, not the `research_config_versions` database table named below, and there is no Admin version selector yet.

## Context

The same rule numbers (target, stop, horizon) are copied about 20 times in the backend and about 8 in the frontend.
A change in one place silently disagrees with the rest. The frontend also counts trading days itself.

## Decision

1. Research numbers (horizons offered, simulation target and stop for research views, score lines, evaluation
   criteria) go in **versioned research config**: immutable rows with a hash (`research_config_versions`). The owner
   approves a new version; old versions are never edited; every score row records the version it used.
2. Admin may only **choose between already validated, versioned options**. Changing a model's target or horizon is
   a retraining and evidence change under a protocol, not a toggle.
3. First step (M6): pure data (`research_params`) plus tests that assert it equals the existing copies. The
   trial-frozen copies are left untouched.
4. The frontend shows backend numbers only (`/config/trading-rules`, trial-journal API) and computes no business
   numbers. Risk limits and live-trading guards are not part of this config. They stay protected code
   (ADR-002, ADR-003).

## Consequences

- One place to read the rule numbers, and tests that catch drift.
- A research change needs a new version and the owner's approval, not an edit.
- Frozen files still hold their own copies until the freeze ends; the equality tests guard them meanwhile.
