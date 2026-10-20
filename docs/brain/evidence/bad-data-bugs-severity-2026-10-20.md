# Severity of the 4 "bolder on bad data" bugs (qa6 drills) — 2026-10-20

Source: `backend/tests/test_bad_data_drills.py` (strict xfail on main). Rated for ps Wave 0 after the
outside review asked that no unsafe path be left alone just to protect the trial.

**What can happen today.** The brain is in practice mode: it places **no orders**
(`strategies/brain.py`, orders only in `services/brain_golive/approvals.py` at stage approval / auto).
So today a bug can only change **what the screen shows** and **what the trial counts**. The share
quantity of a real buy always comes from v1's risk check, never from the brain.

**How often it can happen.** Every bug needs bad data or a module failure first. Since 2026-10-14 the
daily check shows 0 modules dropped on every run, so none of them is known to have fired.

| # | Bug | What goes wrong | Today (practice) | At approval / auto stage | Severity |
|---|---|---|---|---|---|
| 1 | Market judge (M10) fails → backup judges the market from the NIFTY trend only, ignoring breadth | A market that should be DEFENSIVE becomes NORMAL: the 2-idea / half-size limits are dropped and every liked stock is approved | Wrong banner and too many TRADE ideas on screen and in the trial count | More buys at full size in exactly the kind of market the banner exists for | **High** |
| 2 | A decision with no valid stop / target (NaN) passes the final check (constitution) | A TRADE without real levels; the approval stop check `price <= NaN` is always False, so it does not stop it | A TRADE idea with blank levels on screen | A buy whose stop is not a number; what v1's sizing does with it is untested | **High** |
| 3 | A probability outside 0–1 (e.g. 7.0) is accepted | A stock the clean run left at WAIT becomes TRADE | Wrong TRADE idea on screen | A wrong buy candidate | **Medium** (needs a broken module; the fix is one range check) |
| 4 | Decision engine (M08) down and a NaN model score | Stock shows WATCH instead of WAIT | Slightly wrong label; not a TRADE | Not a buy (WATCH never buys) | **Low** |

## Recommendation

Fix all four now, each in the cautious direction (CLAUDE.md principle 5: bad data never makes a decision
bolder):

1. M10 down → the backup judges at least DEFENSIVE when breadth is missing or weak, never NORMAL on trend alone.
2. The constitution turns any TRADE with a missing / non-finite stop or target into WAIT; approvals refuse a
   signal whose levels are not finite numbers.
3. Records with a probability outside 0–1 are rejected (the module's opinion is dropped, as for any bad record).
4. A NaN score counts as "no score" (WAIT).

**Effect on the trial:** on clean data every fix changes nothing (the drills' clean runs stay the same),
so the trial's ideas do not change unless bad data appears — and then the fix is exactly what we want.
Each fix gets its test (the xfail turns into a normal pass) and a row in the trial journal / exposure ledger
stating the date it went live.

Bugs 1 and 2 must be fixed before the stage ever leaves practice, whatever is decided for now.
Needs owner approval (decision and order path).
