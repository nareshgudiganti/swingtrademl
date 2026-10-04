# Brain M17 · Brain Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the owner one screen for the brain: the market banner, today's decisions with a plain-English "how the brain decided", module switches, run health, and a way to overrule a decision toward caution.

**Architecture:** Backend adds four small things behind the existing protected `/api/v1/brain` router: run list, overall data quality stored on each run, failed runs recorded, and an overrule that can only lower a decision. Frontend adds one page `/brain` in the existing style (cards, badges, Modal), wired through `api/client.ts`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest; React 19, TanStack Query 5, TypeScript, Vite.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet M17; sections 15.1 (human override), 16 (API and screens); constitution C8.

## Global Constraints

- Plain English on screen (owner preference: no finance/ML jargon; detail on tap). Words: "fallback" → "simple built-in answer"; "shadow" → "Trial (recorded, not used)"; "trace" → "How the brain decided".
- M07's switch is shown locked ON; the API already refuses OFF (409).
- Overrule may only move a decision to a more cautious word in the same vocabulary (`contracts.rank`); a bolder or equal word is refused (409); a reason is required.
- The page never offers a button that places an order.
- Works at phone width (existing 800px breakpoint).

## Review Focus

1. Overrule to a bolder word (WATCH → TRADE) is refused. (Task 1 test)
2. Overrule with an empty reason is refused. (Task 1 test)
3. A run that crashes is stored as failed and counted in health, instead of vanishing. (Task 1 test)
4. No run yet: the page shows an empty state with a "Run now" button, not an error. (Task 2 browser check)
5. A stock with a very long reason wraps instead of breaking the table on a phone. (Task 2 browser check)

---

### Task 1: Backend — runs list, stored quality, failed runs, overrule, health

**Files:** `db/models/brain.py` (+ columns), new migration `20260930_1800_brain_console.py`, `brain/service.py`, `api/v1/endpoints/brain.py`; tests `test_brain_console_api.py`.

**Interfaces (produced):**
- `BrainRun.quality: dict` — `{"overall": {score, fresh, issues}, "stale": [symbols]}`.
- `BrainDecision.overruled_word / overrule_reason / overruled_by / overruled_at`.
- `service.overrule(db, decision_id, word, reason, by) -> BrainDecision` raising `UnknownDecisionError`, `OverruleRefusedError`.
- `service.health(db) -> dict` — `{last_run, last_nightly_ok, failed_runs_7d, data}`.
- `GET /brain/runs?kind=&limit=`, `GET /brain/runs/{id}`, `POST /brain/decisions/{id}/overrule`, `GET /brain/health`; decision JSON gains `id` and overrule fields.

- [ ] Failing tests: list newest first with counts; quality stored; overrule lowers + stores who/why/when; bolder refused 409; empty reason 422; wrong vocabulary 409; unknown id 404; crashing run stored as `failed` and counted; health shows last run and data issues.
- [ ] Implement; migration upgrade/downgrade on a scratch DB; full suite; commit.

### Task 2: Frontend — `/brain` page

**Files:** `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/pages/Brain.tsx`, `frontend/src/components/icons.tsx` (BrainIcon), `frontend/src/App.tsx` (nav + route), `frontend/src/styles.css` (word pills).

Sections: banner card · health strip · "Run now" + "Why this stock?" · decisions (TRADE, WATCH shown; WAIT/AVOID behind a toggle; holdings) with "How the brain decided" modal and "Overrule" · steps and switches · recent runs.

- [ ] `npm run typecheck` and `npm run build` pass.
- [ ] Run the 8001 API (CORS for 5174) and Vite on 5174; load `/brain` in a headless browser: no console errors, banner and decisions render, the modal opens; phone width does not scroll sideways.
- [ ] Commit.
