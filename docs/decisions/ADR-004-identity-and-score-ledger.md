# ADR-004: One identity per stock, and an append-only score ledger

- **Date**: 2026-11-22
- **Status**: Proposed. Steps 0-1 approved; Steps 2-3 and database changes await the owner. Every migration needs
  the owner's approval in its own PR.
- **Reference**: `docs/architecture/TARGET-ARCHITECTURE-PROPOSAL.md` sections 6 and 9 (M4, M5); GitHub #389
- **Built on `main`** (checked 2026-11-26): `securities`, alias history and `score_ledger` with append-only triggers (`db/models/identity.py:48`, `:96`; migration `20261123_1200_identity_phase1.py`), and the resolver `resolve(db, ..., on_date=None)` (`services/identity/__init__.py:166`). The resolver takes `on_date` as an optional argument, so the point-in-time rule below depends on callers passing it; the read contract is `docs/architecture/IDENTITY-READ-API.md`. `brain_runs.provenance` and the `predictions` RESTRICT change were not checked.

## Context

Stocks are matched by symbol text in several places, so a rename, a merger or a delisting splits history. Score
history is overwritten, and a stored score does not say which model, configuration or code produced it.

## Decision

1. **Stock identity (M4, #389):** a `securities` table with alias history. New tables carry a nullable
   `security_id`; one resolver is used by all new code; existing readers switch one at a time with dual-write.
   **The resolver is point-in-time:** it takes the date the data belongs to (`resolve(symbol, as_of)`) and uses the
   alias history valid on that date, never today's mapping. A replay, a backfill or a historical report resolves
   a reused ticker to the company that held it then. A call without a date is allowed only for "now" (a live
   request) and says so. A test resolves one reused ticker on two dates and expects two different securities.
2. **Score identity (M5):** an append-only `score_ledger` (a trigger rejects UPDATE and DELETE, like the h05
   tables), a `provenance` record on each brain run, and `predictions` referencing models with RESTRICT. Every new
   score, signal and decision row records its model, research-config version and code version.
3. Migrations are forward-compatible (nullable columns first), have a downgrade and a clean-upgrade drill. **The
   lead owns migration ordering and numbering. Developers do not create or renumber migrations.**
4. Writing the ledger from `brain/service._store` touches a trial-frozen file. It waits until after the freeze, or
   a freeze approval is recorded first. Writers outside frozen files (`services/score_history.py`) may go ahead.

## Consequences

- One stock resolves to one `security_id` across Discover, Watchlist, Groww Tracker and Reports.
- Score history can be audited and reproduced; nothing is silently overwritten.
- Temporary duplication (old and new keys side by side) is accepted to keep production safe.
