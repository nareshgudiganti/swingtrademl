# Documentation map

One authoritative document per topic. If you need to know where to look, start here.

| Topic | Authoritative document |
|---|---|
| Current state and status | `docs/brain/PROJECT_COMPLETION_MATRIX.md` (full detail); short summary: `docs/architecture/CURRENT-STATE.md` |
| Architecture and solution (vision vs shipped) | `docs/architecture/TRADEMIND-SOLUTION-OVERVIEW.md` |
| Service 1 (market data and input processing) | `docs/architecture/service-01-market-data.md` |
| Service 1 gaps and their status | `docs/architecture/architecture-gaps.md` (reasoning: `docs/decisions/ADR-001-service-01-gaps.md`) |
| Deploy, rollback, environment | `docs/DEPLOY.md` |
| Quality checks (tests, CI gates) | `docs/QUALITY-CHECKS.md` |
| Brain go-live (practice, approval, auto) | `docs/brain/GO_LIVE.md` |
| Operations, daily and weekly checks, launch | `docs/OPERATIONS-AND-LAUNCH.md` |
| Evidence (reports, protocols, research tools) | `docs/brain/evidence/INDEX.md` |
| Archived (outdated, kept for history) | `docs/archive/README.md` |

Project rules for people and AI agents live in the repo-root `CLAUDE.md` and `AGENTS.md`, not here.

## Precedence rule

1. `CLAUDE.md` (risk rules, settled architecture principles) wins over every other document.
2. For status, `docs/brain/PROJECT_COMPLETION_MATRIX.md` wins over `docs/architecture/CURRENT-STATE.md` (this is what
   `CURRENT-STATE.md` already says). If the matrix is older than recent git history, trust git history and say so.
3. For architecture, `docs/architecture/` wins over anything elsewhere.
4. Signed protocols, amendments and evidence are **records**: they describe what was decided or measured on a date and are
   never edited to match later changes. Anything in `docs/archive/` loses to every live document.

## What is not archived on purpose

Signed or draft protocols, amendments and specs (`docs/superpowers/specs/`), everything under `docs/brain/evidence/`,
`docs/ai/deferred/`, and the plans in `docs/superpowers/plans/` stay where they are.
