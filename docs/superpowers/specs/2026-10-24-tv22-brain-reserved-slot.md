# tv22: one reserved paper slot for the brain — change note for owner approval

Status: **APPROVED by the owner on 2026-10-25 (A–F, F = option (i)). Built on branch
`feature/tv22-reserved-slot`, not yet merged or deployed.** Written 2026-10-24.
Owner decision (2026-10-24): tv22 option (a) — reserve one paper-trading slot for the brain and one for
v1 for the rest of the trial, with the six conditions in section 5.

**Revision 2 — 2026-10-24 (same day).** What changed:

- Found a second gate. The brain's own risk gate **M07** checks room *before* `risk.check_entry` ever sees
  a brain idea, and on DEFENSIVE days it **halves** the size and then refuses anything below the minimum
  position. Revision 1 only touched `risk.check_entry`, so on DEFENSIVE days (every trial day so far) the
  reserved slot would have stayed unusable. Sections 1 and 2 now describe **two layers**.
- New section 2a: three ways to size the reservation so M07 can use it, with a recommendation.
- Also found: a reservation of *exactly* the minimum position fails even on NORMAL days (whole shares are
  rounded down, so the position lands a few rupees under the minimum). The reservation needs one share of
  headroom.
- Section 3 table, section 6 tests and section 7 (new item **F**) updated. Items A–E unchanged.

## 1. The problem in one paragraph

In a stressed market the "market-conditions limit" lets the paper account keep only **10%** of its money
invested (`services/deployable.py`, stressed band). On a ₹9.8L account that is about ₹98K, roughly one or
two positions. The v1 scan runs at **15:45** and uses that room. The brain runs at **15:50**. Its ideas then
meet the limit **twice**:

1. **Inside the brain — M07, the risk gate.** It refuses the idea, and the brain lowers its TRADE to WATCH
   ("risk said no"). The practice brain still records it as a scored idea, tagged `BRAIN_RISK_CHECK`
   (`strategies/brain.py` lines 92–102 and 134–147).
2. **At execution — `risk.check_entry`.** Any TRADE that passed M07 is checked again against the same
   paper account (`services/execution.py` line 1157). If refused, it is tagged `blocked_by_risk_limit`
   (`_mark_blocked_by_risk`, line 998).

Blocked ideas from either layer are scored but do **not** count toward the 30 (`brain_golive/compare.py`,
`COUNT_BLOCKED_TOWARD_GATE = False`). Result so far: 0 counted, 43 blocked.

The position *count* is not the problem: the brain already gets its own share of the position limit
(`risk.py` lines 544–560). The blocker is the **rupee room** under the market-conditions limit (rule
`DEPLOYABLE`), which is account-wide and first come, first served.

### How M07 works out its room (verified in code)

- M07 does **not** ask `check_entry` for its room. It works it out itself, account-wide:
  `brain/modules/m07_risk/module.py` line 92 (`deploy_ceiling` = today's market-conditions fraction × portfolio value), line 91 `invested = sum(h.value for h in holdings)` over **all** open holdings in the
  paper book (line 85, `risk.open_holdings(db, book)` — v1 and brain alike), line 101
  `deploy_room = deploy_ceiling - invested`.
- M07 also calls `risk.check_entry` for each idea, but with **`strategy=None`** (`module.py` lines
  111–120). So `check_entry` cannot tell this call comes from the brain: the brain-vs-v1 test in
  `check_entry` is `strategy.strategy_type in STAGED_TYPES` (`risk.py` line 544), and it is skipped when
  `strategy` is `None` (line 538).
- Inside the allocator, for each idea in order (`allocator.py`):
  line 153 `check(...)` (= `check_entry`, which refuses outright if room < minimum, `risk.py` lines
  671–683, and otherwise sizes the idea to fit the room) → lines 179–181 fit into the sector room →
  line 182 fit into the market-conditions room → **lines 183–185 on DEFENSIVE days halve the quantity**
  (`DEFENSIVE_SIZE_FACTOR = 0.5`, `module.py` line 30) → **line 188 refuse if value < minimum position**.
  At most `DEFENSIVE_MAX_NEW = 2` approvals on a DEFENSIVE day (line 130; `module.py` line 31).

**So: would a reservation added only in `risk.check_entry` be seen by M07?** Not as revision 1 wrote it.
M07 computes its own account-wide room (module.py 92/101) and calls `check_entry` as "no strategy"
(module.py 111–120). If the reservation is keyed on "is the caller the brain?", M07's call looks like a
non-brain caller and would get the *v1* room — reserved room taken off — and be refused. If instead the
reservation is only subtracted for **named v1 strategies**, M07's "no strategy" call sees the whole
account room, which can only include the reserved part once v1 is kept out of it. That is workable without
touching M07, but it is an implicit link and must be pinned by a test (section 6).

**And on DEFENSIVE days M07 needs about twice the minimum position of room.** It sizes the idea to the
room, *then* halves it, *then* demands the full minimum. Prod 2026-10-24: banner DEFENSIVE on every trial
day so far; minimum position ₹39,734; ceiling ₹97,579 (10%, stressed); room left ₹13,278. A brain idea
there needs roughly ₹79,500 + one share of room to survive M07 — not ₹39,734.

## 2. What "reserve one slot" would mean in code — two layers that must agree

Both layers must use the same reserved room. If only one of them knows about it, the slot stays unusable.

**Layer 1 — execution (`services/risk.check_entry`), market-conditions section (`risk.py` lines 670–684):**

- **v1 strategies** (a named, non-staged strategy): room = ceiling − invested − *brain reservation*,
  unless the brain already holds a position using it.
- **brain** (staged strategy): room = the lesser of (reservation − what the brain already holds) and
  (ceiling − invested). The account total can never go above today's ceiling.
- **calls with no strategy** (today only M07): room = ceiling − invested, unchanged. Because v1 is kept out
  of the reserved part, this whole-account room already contains it.
- `engine._buy_slot_budget` mirrors the same rule so the v1 scan does not try buys that `check_entry` will
  refuse.

**Layer 2 — inside the brain (M07).** Depends on the sizing option chosen in section 2a. Under the
recommended option (i), M07's code is **not changed**: its own room (module.py line 101) is the whole
account's room, which contains the reservation once v1 is kept out of it.

**The size of the reservation** is the open question — section 2a.

Nothing else: no change to stops, targets, the sizing formula, kill switch, drawdown halt, sector cap,
cash floor, approval flow, or real-money code.

**When it starts working.** The reservation only stops *new* v1 buys from using the room. Today v1
already holds about ₹84,300 of the ₹97,579 ceiling. Nothing is sold to make room (condition 2, "never
force"). So the reserved room appears only as v1 positions close — this could take days or weeks.

## 2a. How big must the reservation be? Three options

Whole-share rounding applies in every option: the reservation must be the minimum **plus one share** of
the idea's price, or the fitted position lands just under the minimum and is refused (`_size` rounds down,
`risk.py` lines 404–405; allocator line 89).

### (i) Reserve twice the minimum on DEFENSIVE days — no M07 change (recommended)

Reservation = minimum position + one share on NORMAL days; **2 × minimum + headroom** on DEFENSIVE days
(the factor 2 = 1 ÷ M07's `DEFENSIVE_SIZE_FACTOR`, kept in one helper in `risk.py`, with a test that fails
if M07's factor ever changes).

- Pros: M07 and its rules are untouched; the brain's DEFENSIVE idea is still half size and still at least
  the full minimum, exactly as today. Nothing becomes bolder — positions are no bigger, no floor is lowered.
  Moves only toward caution, as CLAUDE.md requires.
- Cons: **costs v1 a lot of room in a stressed market.** On prod numbers, ~₹80K reserved out of ₹97,579
  leaves v1 about ₹18K — below its ₹39,734 minimum — so **v1 makes no new buys while the market is stressed
  and DEFENSIVE** (until the ceiling rises). v1's trial results change accordingly. Also relies on the
  "no strategy = whole-account room" link (section 1), which needs a test.
- One more thing to decide (item F): in later stages (manual approval / auto) the real paper order is sized
  by `check_entry` (`strategies/brain.py` line 116: M07's quantity is "informational only"), which does not
  halve on DEFENSIVE days. With a 2× reservation the order could be ~2× the size M07 meant. Not a problem in
  practice stage (no orders), but it must be settled — e.g. cap the order at M07's quantity — **before**
  the stage moves past practice.

### (ii) Change M07: halve before fitting, or compare with a halved minimum

Either halve the quantity *before* fitting it into the room, or compare the halved size with half the
minimum. Reservation could then stay at one minimum + one share.

- Pros: v1 keeps far more room (gives up ~₹40K, not ~₹80K).
- Cons: **frozen-file change to the brain's risk gate** (`allocator.py`, in `trial_freeze.json`), and
  **bolder sizing**: "halve before fitting" means that on a tight-room DEFENSIVE day the defensive halving no
  longer shrinks anything; "halved minimum" allows positions *below* the account's minimum, where fixed
  charges eat more of the trade. Both loosen a caution rule mid-trial. **Owner-only decision**; not
  recommended.

### (iii) Make M07 read the brain's reserved room directly

One shared helper in `risk.py` ("room for the brain"), used by M07's `account_snapshot` (module.py line
101), and M07 passes the brain strategy to `check_entry` instead of `None` (module.py line 119).

- Pros: one definition of the brain's room in both layers — no implicit link; easiest to reason about.
- Cons: frozen-file change to `module.py`; passing the brain strategy also changes what else M07's check
  does (brain position share, per-strategy cool-down, sizing overrides), so M07's behaviour moves in ways
  beyond the reservation. And it does **not** solve the halving on its own — it still needs (i)'s 2× size,
  or (ii). Worth doing later as a tidy-up; not needed now.

**Recommendation: option (i).** It is the only option that keeps every brain caution rule exactly as it is
and touches no brain file. Its honest cost is that v1 stops opening new positions while the market is
stressed and DEFENSIVE — a large change to the v1 trial that the owner must accept knowingly (item F). If
that cost is too high, the honest alternative is **not** (ii) but declining the reservation on DEFENSIVE
days (brain gets a slot only on NORMAL days) — cautious, but on current evidence the brain would then
count nothing until the market improves.

## 3. Answer to the owner's question: what does it change?

| Area | Changes? | Detail |
|---|---|---|
| **Frozen trial code** | **Yes** | Option (i): `services/risk.py` and `services/engine.py` only (both in `tests/trial_freeze.json`). `brain/modules/m07_risk/allocator.py` and `module.py` are also frozen (`trial_freeze.json` lines 59–60) but are **not** touched under (i). Option (ii) adds `allocator.py`; option (iii) adds `module.py`. The freeze test fails until each change is recorded with `scripts/approve_trial_change.py` after owner approval. |
| **v1 trial behaviour** | **Yes — large under (i)** | Stressed + DEFENSIVE (every day so far): v1 loses ~₹80K of a ~₹98K ceiling and in practice makes **no new buys** until the ceiling rises. Stressed + NORMAL: v1 loses ~₹40K + one share. Normal markets: small effect. |
| **Brain trial counter (30 ideas)** | **Yes, but not at once** | From the change date, a brain TRADE idea that passes M07 **and** `check_entry` inside the reserved room is "placeable" and counts (subject to fx2, section 4). It only becomes possible once v1's existing holdings have closed enough to free the reserved room (today ₹13,278 free vs ~₹80K needed), so the counter may stay at 0 for days or weeks after the change. The 43 ideas already blocked stay blocked; nothing is relabelled backwards. |
| **Forward-trial pass rule (layer-2 5a)** | **Needs a written amendment** | The 15 sessions / 30 ideas start on 14 Oct. Ideas before and after the change date were judged under different room rules. Proposal: record the change date in the trial journal and report the two periods separately; the gate's numbers are unchanged. |
| **5-day protocol (fd-protocol-v1)** | **Yes — decides D6** | D6 is "forward test in a book of its own, decide with tv22". Option (a) is a *shared account with a reserved slot*, not an own book. D6 must be signed as that before the 5-day forward test starts, and the reduced v1 room becomes part of what the 5-day test measures. |
| **Evidence plan Phase B / walk-forward / horizon experiment** | No | Those are historical replays or owner-picked ledgers; they do not read the live paper account. |
| **Portfolio accounting** | No | In practice stage the brain places no orders, so cash, ledger and positions are untouched. The reservation is a rule inside the risk check only. Every position already carries its `strategy_id`, so brain and v1 results stay separate. A true separate book (own cash) would be the multi-user portfolio work (mu3) — not needed for (a). |
| **Real money** | No | Real orders (`ALLOW_REAL_HOLDINGS_ORDERS`, My Holdings) are a different path and are not touched. |

## 4. One thing that must be decided together with this: fx2 (how ideas are counted)

In practice stage the brain never holds a position, so its reserved room is **always free** (once v1 has
freed it). Without a counting rule, every brain TRADE idea that fits one position would count — the same
stock again each day — and the 30 could fill in a few days with mostly repeats. That would not be "one
slot". (M07 itself already allows at most one idea into a 2× reservation on DEFENSIVE days, but on NORMAL
days and across days repeats remain.)

Recommendation: decide fx2 at the same time. Simplest rule that matches "one slot": **in practice stage,
at most one new counted brain idea per day — the highest-ranked TRADE idea that passes every risk check —
and a stock that is already a counted, unfinished idea is not counted again.** Every other TRADE idea is
still recorded and scored, tagged as "beyond the reserved slot", and reported separately like the blocked
ones (condition 3).

## 5. The owner's conditions and how each is met

1. *Paper only; real orders untouched.* Only the paper risk check changes; a test proves real-order code
   paths are not reached.
2. *Never force a trade.* The reservation only leaves room; if the brain has no TRADE idea that passes
   every check, the room stays empty. No v1 position is sold to create room. Test: no brain idea → no
   order, room unused.
3. *Track ML and v1 independently, including blocked and rejected.* Already true by `strategy_id` and the
   two blocked tags (`BRAIN_RISK_CHECK` from M07, `blocked_by_risk_limit` from `check_entry`); adds a
   "beyond reserved slot" tag (section 4). Compare page and evidence pack show all of them.
4. *All existing risk checks, approvals and kill switch stay.* The reservation is applied after the kill
   switch, drawdown halt and position limits, inside the existing market-conditions limit — the account
   total can never go above today's ceiling. Under option (i) M07's defensive halving and minimum stay
   exactly as they are. Test: account invested never exceeds the ceiling.
5. *Freeze the allocation before results.* Change is recorded in `trial_freeze.json`, the change date in
   the trial journal, and the 5-day protocol tag `fd-protocol-v1` is cut after it — all before any trial
   result is read (results stay sealed, `services/trial_seal.py`).
6. *5-day and 15-day evidence reported separately.* Already true (`/brain/compare` `scored_on`, fx3);
   kept.

## 6. Tests to write before it can merge

- **End to end, DEFENSIVE day:** with v1 holdings filling everything but the reservation, a brain TRADE
  idea passes **M07** (allowed verdict, half size, value ≥ minimum) **and** `check_entry` at execution, and
  is counted as placeable — not tagged `BRAIN_RISK_CHECK` or `blocked_by_risk_limit`. Same test on a NORMAL
  day with the 1× reservation.
- Same setup, a second brain idea on the DEFENSIVE day is refused by M07 (only one fits the reserved room).
- Whole-share rounding: a reservation of exactly the minimum is refused; minimum + one share passes.
- M07's `check_entry` call with no strategy sees the whole-account room (pins the implicit link in
  section 1); a named v1 strategy sees the room minus the reservation.
- The reservation helper's DEFENSIVE multiplier equals 1 ÷ M07's `DEFENSIVE_SIZE_FACTOR` (fails if either
  changes alone).
- v1 cannot use the reserved room in a stressed market; the brain can.
- Account total invested never exceeds the market-conditions ceiling, with or without the reservation.
- Kill switch / drawdown halt / NO_NEW_TRADES banner still refuse the brain's reserved slot.
- Practice stage: at most one counted idea per day (if fx2 rule adopted); the rest tagged and scored.
- No brain idea → no order; no change to real-order paths.
- Freeze test passes only after `approve_trial_change.py` is run with the owner's reason; under option (i)
  the freeze hashes for `allocator.py` and `module.py` are unchanged.

## 7. What the owner needs to approve

- [x] A. The change in section 2 (frozen-file change during the trial).
- [x] B. The trial-journal amendment: record the change date, report before/after separately (section 3).
- [x] C. fx2 counting rule in section 4 (or another rule).
- [x] D. 5-day protocol D6 = "shared paper account, one slot reserved for the brain" (section 3).
- [x] E. Deploy timing: outside 09:00–16:30 IST, after CI and the after-deploy smoke test are green.
- [x] F. Sizing choice (section 2a): **(i)** reserve 2× minimum on DEFENSIVE days, accepting that v1 makes
      no new buys while stressed and DEFENSIVE (recommended); or (ii) change M07's halving (owner-only,
      bolder); or reserve on NORMAL days only. Also: before the stage moves past practice, cap a brain order
      at M07's half-size quantity on DEFENSIVE days.

**Approved by the owner on 2026-10-25:** A, B, C, D and E as written; F = option **(i)** (reserve minimum +
one share on NORMAL days and 2 × minimum + headroom on DEFENSIVE days, accepting that v1 makes no new buys
while stressed and DEFENSIVE), plus the cap of a brain order at M07's half-size quantity on DEFENSIVE days
before the stage moves past practice (built with the change).

Build notes (decided while building, for the owner's review):

- DEFENSIVE headroom is one share **per half**: reservation = (minimum + one share) ÷ M07's factor = 2 ×
  minimum + 2 shares. With only one share, M07's round-down halving can still land under the minimum
  (e.g. a ₹3,000 share: 27 shares fit, half is 13 = ₹39,000 < ₹39,734). Tested.
- The day's mode comes from the brain's latest finished live nightly run (`brain_runs.banner_mode`). No
  run, or NO NEW TRADES, is read as DEFENSIVE (the larger, cautious reservation). v1's 15:45 scan reads the
  previous day's banner, the brain's 15:50 checks read that day's.
- Nothing is reserved when no brain strategy is active in that book (e.g. the live book).
- "One share" is the share price of the idea being checked (v1's own stock for a v1 buy).
- `engine._buy_slot_budget` caps buys at the rupee room ÷ minimum, without the one-share headroom (it has
  no price yet), and always tries at least one candidate so check_entry still records the real refusal.
- Trial journal change date: `TV22_CHANGE_DATE = 2026-10-26` (`brain/trial_journal.py`); move it to the
  first session after the real deploy if the deploy slips, before any trial result is read.
