# Brain M07 · Risk and Safety Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the brain its mandatory risk gate, so a stock the brain likes gets an approved size (or a plain-English refusal) from version 1's own risk rules, judged as one batch so the approvals fit the account together.

**Architecture:** A pure batch allocator (`allocate`) ranks candidates and walks them strongest-first, keeping a running tally of cash, free slots, sector room and invested money; for each candidate it calls an injected `check` (in production, v1's `risk.check_entry` with the remaining cash) and then applies only the batch ceilings `check_entry` cannot see. A thin module (`M07`) builds candidates from the context, builds the account snapshot from the database, and turns the allocator's output into `RiskVerdict@1` records. Market mode shapes the batch: DEFENSIVE halves size and caps the count; NO NEW TRADES refuses all.

**Tech Stack:** Python 3.12, SQLAlchemy 2, pytest, existing `services/risk.py`, `services/limits.py`, `services/deployable.py`, `services/portfolio.py`.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet M07, sections 10 (module contract), 11 (fallbacks), 15 (constitution C1–C3).

## Global Constraints

- M07 is `mandatory=True`, step `risk`, kind `step`, id `"M07"`; it is the only module allowed to write `RiskVerdict@1` (runner already enforces).
- Stop for sizing = entry × 0.96 (locked −4% rule); target is not M07's concern.
- M07 never writes to v1 tables and never imports `swing_trade_ml.brokers` or `swing_trade_ml.services.execution` directly (import-lint test exists).
- DEFENSIVE: size × 0.5, at most 2 new approvals per run. Both are named constants.
- Every refusal carries a stable `rule` code and a plain-English `reason` (NFR-14).
- Replays (`request.live is False`) never approve: risk state is "now" data.
- Deterministic: same inputs → same verdicts (sort by strength desc, then symbol).

## Review Focus

1. Two candidates in the same sector that each fit alone but not together → the weaker is shrunk to the remaining room or refused `SECTOR_CAP`. (Task 1 test)
2. More liked stocks than free position slots → the weakest are refused `POSITION_LIMIT` with "a stronger idea took the last slot". (Task 1 test)
3. Cash runs out part-way through the batch → later candidates are refused, never over-approved. (Task 1 test: `check` receives the remaining cash)
4. `check_entry` raises for one stock (bad data, missing instrument) → that stock is refused `ERROR`, the rest are still judged. (Task 1 test)
5. A liked stock with no price snapshot, or with stale data → refused (`NO_PRICE` / `DATA`), never sized from nothing. (Task 2 test)

---

## File Structure

- Create `backend/src/swing_trade_ml/brain/modules/__init__.py` — imports every installed module so registration happens on import.
- Create `backend/src/swing_trade_ml/brain/modules/m07_risk/__init__.py` — empty package marker.
- Create `backend/src/swing_trade_ml/brain/modules/m07_risk/allocator.py` — pure batch allocator: `Candidate`, `Account`, `CheckResult`, `Policy`, `allocate()`.
- Create `backend/src/swing_trade_ml/brain/modules/m07_risk/module.py` — `RiskGate(BrainModule)`: candidates from the context, account from the DB, `check` wrapping `risk.check_entry`.
- Modify `backend/src/swing_trade_ml/brain/service.py` — import `swing_trade_ml.brain.modules` so the registry is populated.
- Modify `backend/src/swing_trade_ml/brain/reader.py` — add `instrument_id(symbol)`.
- Tests: `backend/tests/test_brain_m07_allocator.py` (pure), `backend/tests/test_brain_m07_module.py` (DB), update `backend/tests/test_brain_api.py` (modules list now has M07).

---

### Task 1: Pure batch allocator

**Files:**
- Create: `backend/src/swing_trade_ml/brain/modules/__init__.py` (empty for now), `backend/src/swing_trade_ml/brain/modules/m07_risk/__init__.py`, `backend/src/swing_trade_ml/brain/modules/m07_risk/allocator.py`
- Test: `backend/tests/test_brain_m07_allocator.py`

**Interfaces:**
- Produces:
  - `Candidate(symbol: str, price: float, strength: float, bucket: str | None, instrument_id: int | None = None)`
  - `Account(portfolio_value: float, cash: float, free_slots: int, min_position_inr: float, sector_rule: str, sector_cap_pct: float | None, sector_exposure: dict[str, float], deploy_room: float)`
  - `CheckResult(allowed: bool, qty: int = 0, rule: str | None = None, reason: str = "", amount_inr: float | None = None)`
  - `Policy(mode: MarketMode, defensive_size_factor: float = 0.5, defensive_max_new: int = 2)`
  - `allocate(candidates, account, check: Callable[[Candidate, float], CheckResult], policy, buy_cost: Callable[[float, int], float]) -> list[RiskVerdict]`

- [ ] **Step 1: Write the failing tests** (`test_brain_m07_allocator.py`): ranking by strength then symbol; NO_NEW_TRADES refuses all; free-slot limit refuses the weakest with "stronger idea"; `check` receives cash reduced by earlier approvals; cumulative sector room shrinks then refuses; `one_per_sector` refuses a second approval in the same bucket; deploy room shrinks; DEFENSIVE halves size and caps count at 2; below-minimum after shrink → refused with the binding rule; `check` raising → `ERROR` for that stock only; refusals carry reasons.
- [ ] **Step 2: Run** `pytest tests/test_brain_m07_allocator.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `allocator.py` (algorithm below).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the brain risk gate's batch allocator`.

Algorithm:

```
order = sorted(candidates, key=(-strength, symbol))
if mode is NO_NEW_TRADES: refuse all "MARKET"
cash_left, slots_left, deploy_left = account.cash, account.free_slots, account.deploy_room
sector_used = copy(account.sector_exposure); approved_buckets = set(); approved = 0
for cand in order:
    if mode is DEFENSIVE and approved >= defensive_max_new: refuse "DEFENSIVE_LIMIT"
    if slots_left <= 0: refuse "POSITION_LIMIT" (stronger ideas took the free slots)
    try: r = check(cand, cash_left)            # v1 rules against the remaining cash
    except Exception: refuse "ERROR"; continue
    if not r.allowed: refuse r.rule/r.reason; continue
    qty, binding = r.qty, None
    if cand.bucket:
        if sector_rule == "one_per_sector" and cand.bucket in approved_buckets: refuse "SECTOR_CAP"
        if sector_cap_pct is not None:
            room = sector_cap_pct * pv - sector_used[bucket]; qty, binding = shrink(qty, room, "SECTOR_CAP")
    qty, binding = shrink(qty, deploy_left, "DEPLOYABLE")
    if mode is DEFENSIVE: qty = floor(qty * defensive_size_factor); binding = binding or "DEFENSIVE_SIZE"
    if qty < 1 or qty * price < min_position_inr: refuse binding or "MIN_POSITION"
    approve(qty); cash_left -= buy_cost(price, qty); slots_left -= 1
    sector_used[bucket] += qty*price; deploy_left -= qty*price; approved_buckets.add(bucket); approved += 1
```

### Task 2: M07 module wired to v1 risk and the database

**Files:**
- Create: `backend/src/swing_trade_ml/brain/modules/m07_risk/module.py`
- Modify: `backend/src/swing_trade_ml/brain/modules/__init__.py` (import m07), `backend/src/swing_trade_ml/brain/service.py` (import modules), `backend/src/swing_trade_ml/brain/reader.py` (`instrument_id`)
- Test: `backend/tests/test_brain_m07_module.py`; update `backend/tests/test_brain_api.py`

**Interfaces:**
- Consumes: `allocate`, `Candidate`, `Account`, `CheckResult`, `Policy` from Task 1; `risk.check_entry`, `risk.open_holdings`, `risk.open_position_count`, `risk.buy_cost`, `limits.limits_for`, `deployable.current_deployable`, `portfolio.portfolio_value_and_cash`, `sector_map.get_sector_bucket`.
- Produces: `RiskGate` registered as `M07`; `candidates_from(view) -> tuple[list[Candidate], list[RiskVerdict]]` (early refusals for missing price / stale data); `DatedReader.instrument_id(symbol) -> int | None`.

Candidate rule: per symbol, prefer an opinion from source `"combined"`, else `"model"`, else the highest stance. It is a candidate when `probability >= threshold` (both present) or else `stance > 0`. Strength = probability if present, else `(stance + 1) / 2`.

- [ ] **Step 1: Write the failing tests:** replay refuses with `REPLAY`; a liked stock without a snapshot → `NO_PRICE`; stale data → `DATA`; with a seeded paper account and `deployable` patched flat, a liked stock is approved with qty > 0 and the run's banner leaves NO NEW TRADES; M07 appears in `GET /brain/modules` as mandatory; `PUT /brain/modules/M07 {"mode":"off"}` → 409.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** module, registration, reader method.
- [ ] **Step 4: Run** the M07 tests, then the full suite → PASS.
- [ ] **Step 5: Commit** `Add the brain's mandatory risk gate (M07)`.

### Task 3: Local check on the scratch database

- [ ] Copy the active model file(s) out of the Docker volume to a local folder and point the scratch database's `ml_models.artifact_path` at it (scratch DB only).
- [ ] Run `swingtrade brain run --kind nightly` against `brain_m00_check`; expect banner NORMAL or DEFENSIVE, liked stocks WATCH with a size and "data quality was not checked" (M01 not built), refusals with reasons.
- [ ] Restart the port-8001 server on the M07 branch; record results in the handoff.

## Deferred (named so they are not lost)

- Holdings pass-through of v1 exit state (build book M07 step 5) → moves to M08/M15, which own holding words.
- Per-strategy position share: the brain has no Strategy row until M18, so `check_entry` runs with `strategy=None` (large-cap tier, account-wide slots).
