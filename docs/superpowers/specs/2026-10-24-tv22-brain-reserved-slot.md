# tv22: one reserved paper slot for the brain — change note for owner approval

Status: **DRAFT, awaiting owner approval. Nothing is built.** Written 2026-10-24.
Owner decision (2026-10-24): tv22 option (a) — reserve one paper-trading slot for the brain and one for
v1 for the rest of the trial, with the six conditions in section 5.

## 1. The problem in one paragraph

In a stressed market the "market-conditions limit" lets the paper account keep only **10%** of its money
invested (`services/deployable.py`, stressed band). On a ₹9.8L account that is about ₹98K, roughly one or
two positions. The v1 scan runs at **15:45** and uses that room. The brain runs at **15:50**; each of its
TRADE ideas goes through the same `risk.check_entry` against the same paper account, finds no room, and is
tagged `blocked_by_risk_limit` (`services/execution.py::_mark_blocked_by_risk`). Blocked ideas are scored
but do **not** count toward the 30 (`brain_golive/compare.py`, `COUNT_BLOCKED_TOWARD_GATE = False`).
Result so far: 0 counted, 43 blocked.

The position *count* is not the problem: the brain already gets its own share of the position limit
(`risk.py` lines 544–560). The blocker is the **rupee room** under the market-conditions limit (rule
`DEPLOYABLE`), which is account-wide and first come, first served.

## 2. What "reserve one slot" would mean in code

1. In `risk.check_entry`, market-conditions section:
   - **v1 strategies** (not staged): room = ceiling − invested − *brain reservation*, where the brain
     reservation is one position's worth (the account tier's minimum position, or the brain's current
     holdings if larger) unless the brain already holds a position using it.
   - **brain** (staged): room = the reservation − what the brain itself already holds.
2. `engine._buy_slot_budget` mirrors the same rule so the v1 scan does not try buys that `check_entry` will
   refuse.
3. Nothing else: no change to stops, targets, sizing formula, kill switch, drawdown halt, sector cap,
   cash floor, approval flow, or real-money code.

## 3. Answer to the owner's question: what does it change?

| Area | Changes? | Detail |
|---|---|---|
| **Frozen trial code** | **Yes** | `services/risk.py` and `services/engine.py` are in `tests/trial_freeze.json`. The freeze test fails until the change is recorded with `scripts/approve_trial_change.py` after owner approval. |
| **v1 trial behaviour** | **Yes** | In a stressed market v1 loses about one position's worth of room. v1 will buy less than it would have. In normal markets the effect is small (room is larger). |
| **Brain trial counter (30 ideas)** | **Yes** | From the change date, brain TRADE ideas that fit the reserved room are "placeable" and count. The 43 ideas already blocked stay blocked; nothing is relabelled backwards. |
| **Forward-trial pass rule (layer-2 5a)** | **Needs a written amendment** | The 15 sessions / 30 ideas start on 14 Oct. Ideas before and after the change date were judged under different room rules. Proposal: record the change date in the trial journal and report the two periods separately; the gate's numbers are unchanged. |
| **5-day protocol (fd-protocol-v1)** | **Yes — decides D6** | D6 is "forward test in a book of its own, decide with tv22". Option (a) is a *shared account with a reserved slot*, not an own book. D6 must be signed as that before the 5-day forward test starts, and the reduced v1 room becomes part of what the 5-day test measures. |
| **Evidence plan Phase B / walk-forward / horizon experiment** | No | Those are historical replays or owner-picked ledgers; they do not read the live paper account. |
| **Portfolio accounting** | No | In practice stage the brain places no orders, so cash, ledger and positions are untouched. The reservation is a rule inside the risk check only. Every position already carries its `strategy_id`, so brain and v1 results stay separate. A true separate book (own cash) would be the multi-user portfolio work (mu3) — not needed for (a). |
| **Real money** | No | Real orders (`ALLOW_REAL_HOLDINGS_ORDERS`, My Holdings) are a different path and are not touched. |

## 4. One thing that must be decided together with this: fx2 (how ideas are counted)

In practice stage the brain never holds a position, so its reserved room is **always free**. Without a
counting rule, every brain TRADE idea that fits one position would count — the same stock again each day,
up to ~50 a day — and the 30 could fill in a few days with mostly repeats. That would not be "one slot".

Recommendation: decide fx2 at the same time. Simplest rule that matches "one slot": **in practice stage,
at most one new counted brain idea per day — the highest-ranked TRADE idea that passes every risk check —
and a stock that is already a counted, unfinished idea is not counted again.** Every other TRADE idea is
still recorded and scored, tagged as "beyond the reserved slot", and reported separately like the blocked
ones (condition 3).

## 5. The owner's conditions and how each is met

1. *Paper only; real orders untouched.* Only the paper risk check changes; a test proves real-order code
   paths are not reached.
2. *Never force a trade.* The reservation only leaves room; if the brain has no TRADE idea that passes
   every check, the room stays empty. Test: no brain idea → no order, room unused.
3. *Track ML and v1 independently, including blocked and rejected.* Already true by `strategy_id` and the
   blocked tag; adds a "beyond reserved slot" tag (section 4). Compare page and evidence pack show both.
4. *All existing risk checks, approvals and kill switch stay.* The reservation is applied after the kill
   switch, drawdown halt and position limits, inside the existing market-conditions limit — the account
   total can never go above today's ceiling. Test: account invested never exceeds the ceiling.
5. *Freeze the allocation before results.* Change is recorded in `trial_freeze.json`, the change date in
   the trial journal, and the 5-day protocol tag `fd-protocol-v1` is cut after it — all before any trial
   result is read (results stay sealed, `services/trial_seal.py`).
6. *5-day and 15-day evidence reported separately.* Already true (`/brain/compare` `scored_on`, fx3);
   kept.

## 6. Tests to write before it can merge

- v1 cannot use the reserved room in a stressed market; the brain can.
- Account total invested never exceeds the market-conditions ceiling, with or without the reservation.
- Kill switch / drawdown halt still refuse the brain's reserved slot.
- Practice stage: at most one counted idea per day (if fx2 rule adopted); the rest tagged and scored.
- No brain idea → no order; no change to real-order paths.
- Freeze test passes only after `approve_trial_change.py` is run with the owner's reason.

## 7. What the owner needs to approve

- [ ] A. The change in section 2 (frozen-file change during the trial).
- [ ] B. The trial-journal amendment: record the change date, report before/after separately (section 3).
- [ ] C. fx2 counting rule in section 4 (or another rule).
- [ ] D. 5-day protocol D6 = "shared paper account, one slot reserved for the brain" (section 3).
- [ ] E. Deploy timing: outside 09:00–16:30 IST, after CI and the after-deploy smoke test are green.
