# M14 Portfolio Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Look at all positions together — which holdings and ideas move together, how concentrated the book is — demote ideas that would double up on what you hold (or on a stronger idea in the same run), and show exposure after a planned trade.

**Architecture:** Pure `correlation.py` (dated closes → 60-day return correlations, close pairs, concentration). A STATE plug-in fills `PortfolioState` (correlated pairs, largest position, top sector) and writes a `portfolio` *modifier* opinion per idea ("Moves closely with HDFCBANK, which you already hold"). The risk gate's allocator judges an idea that moves with a stronger idea of the same run after the others, with a note on its verdict that M08 shows. Opportunity cost already lives in M08 (`opportunity_notes`). `POST /brain/whatif`; a portfolio panel on the console.

**Spec:** build book, module sheet "M14 Portfolio brain".

## Global Constraints
- Plug-in, Wave 4, step 2 State + 7 Decide. Correlation of 60-day returns; flag > 0.7. Concentration against `limits_for()`. Re-rank: prefer diversifiers, demote highly correlated (reason given). Opportunity cost in words only. What-if endpoint. Off → no correlation checks (sector cap still in M07).
- Modifiers never decide (brain/opinions.py). Never bolder.

## Review Focus
1. Two perfectly correlated candidates → the second is judged after the others — Task 3 `test_a_candidate_moving_with_a_stronger_one_is_judged_last`.
2. Too little shared history (< 40 overlapping days) → no correlation claimed — Task 1 `test_too_little_overlap_claims_nothing`.
3. No holdings → no "adds variety" lines (nothing to diversify from) — Task 2 `test_without_holdings_there_is_nothing_to_compare`.
4. What-if for a stock already held adds to its existing share — Task 4 `test_whatif_adds_to_an_existing_holding`.
5. Opportunity-cost note only when slots are full — already covered by M08 tests (`opportunity_notes`).

Tasks: (1) correlation.py + concentration; (2) contract fields, module, `portfolio` modifier; (3) allocator ordering + verdict note shown by M08; (4) what-if endpoint, run context + console panel; (5) real check, notes, memory.
