# Brain M08 · Decision Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn everything the earlier steps know into the final word for every stock (TRADE / WATCH / WAIT / AVOID) and every holding (HOLD / MONITOR / REDUCE / EXIT), with an entry zone, levels, an honest evidence sentence, an expected result in R when real hit rates exist, and opportunity-cost notes — through a rule list the owner can extend or switch off rule by rule.

**Architecture:** Pure engine. Each stock starts as a draft (liked → TRADE with levels and the risk gate's size; otherwise WAIT with why) and passes through an ordered list of named `Rule`s. A rule only proposes a more careful word and a reason; the engine applies it with `contracts.downgrade`, so no rule can ever make a decision bolder. Adding a rule = one function in the list; removing = its id in `DecidePolicy.disabled`. Holdings use the same mechanism. Module `M08` (step `decide`) gathers the facts from the context and writes decisions and the banner; the decide fallback fills anything M08 left out; the constitution still runs last.

**Tech Stack:** Python 3.12, pytest; `brain/contracts.py`, `services/costs.py`.

**Spec:** build book module sheet M08; section 7 (vocabulary, horizon, evidence wording); constitution C6, C7, C12. Owner decision 2026-10-01: vocabulary Option A; rules must be addable and removable.

## Global Constraints

- Vocabulary Option A only. Locked rule: target +8%, stop −4%, first target +5% (book half), horizon 15 trading days.
- Entry zone = close ± min(0.25 × ATR, 1% of close); target = close × 1.08; stop = close × 0.96.
- Expected result in R (1 R = the 4% risked): `EV = p × 2 − (1 − p) × 1 − cost_pct / 0.04`, only when a recall with n ≥ 30 gives `p`; otherwise no EV and the evidence line says so.
- A stop already hit is reported as "Stop hit", never offered as a choice (C7). No promise words (C12).
- Opportunity cost is words only; nothing is sold automatically.

## Review Focus

1. A rule can never raise a decision (TRADE stays the ceiling). (Task 1 test)
2. Disabling a rule by id removes exactly that rule's effect. (Task 1 test)
3. A holding whose price is at or below its stop says "Stop hit" and EXIT. (Task 1 test)
4. A model score is not a probability: without similar-case evidence no EV is shown and the evidence line says why. (Task 1 test)
5. With every module off except M08, the brain still decides every stock. (Task 2 test)

### Task 1: Pure engine and rules
Files: `brain/contracts.py` (Holding gains `stop`, `target`, `scaled_out`), `brain/reader.py` (holdings carry them), `brain/modules/m08_decide/{__init__,policy,engine,rules}.py`; tests `test_brain_m08_engine.py`.
- [ ] Failing tests for drafts, levels, each rule, disabling, monotonicity, evidence, EV, holdings rules, opportunity notes.
- [ ] Implement; commit.

### Task 2: Module and local check
Files: `m08_decide/module.py`, `brain/modules/__init__.py`; tests `test_brain_m08_module.py`; API module-list test.
- [ ] Failing tests: registered in DECIDE; with M07 + quality it produces TRADE with zone and evidence; the banner comes from M08; holdings get words.
- [ ] Implement; full suite; lint; commit; local run on the check DB; restart the console API.
