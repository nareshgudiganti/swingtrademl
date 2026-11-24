# #252 Verification: capital limits, position sizing and allocation

Baseline commit: `7ba3547` (main). Test database: `swing_trade_ml_dev4b_test`. Written 2026-11-24 (IST).
Method: the review-risk checklist (verdict, limits checked, hard-coded values, test coverage). Tests and this note only;
no risk, sizing, limit, order or frozen code was changed. Account sizes checked: Rs 10,000, 25,000, 1,00,000, 10,00,000 and
1,00,00,000 (Rs 1 crore). Rs 10K, 1L, 10L and 1Cr are ladder rungs; Rs 25K sits between two rungs (blended on a log scale).

## Verdict

**Safe as it stands, with one gap (issue #463) and three things to know. Nothing was changed, so nothing here needs owner approval to
merge; fixing the gap would (it touches limits).**

## In plain English

- **The ladder works and scales.** The number of positions, the minimum position, the biggest share in one stock and the
  cash reserve all move in the right direction as the account grows, and nothing is ever looser than the published rungs.
  The 25% one-sector cap and the 15% drawdown halt are in force at every size.
- **Sizes never overshoot.** For every size and a spread of share prices, a position is rounded *down* to whole shares, so
  it never passes the single-stock cap, never risks more than 1% of the account at the stop, and never spends more cash
  than there is (charges included).
- **Why the Rs 10K and Rs 25K accounts never trade (accepted by the owner).** The rule risks 1% of the account on each trade
  and the stop is 4% away, so a trade is 25% of the account: Rs 2,500 at Rs 10K, about Rs 6,250 at Rs 25K. The minimum
  position (the size below which fixed charges eat the trade) is Rs 4,000 at Rs 10K and about Rs 8,400 at Rs 25K. A Rs 2,500
  trade is below Rs 4,000, so it is always refused. This stops being true at about Rs 43,000; at Rs 1,00,000 the trade is
  Rs 25,000 against a Rs 15,000 minimum.
- **From Rs 10 lakh up, the single-stock cap is tighter than the 1% rule,** so a stop-out costs about 0.4% (Rs 10L) or 0.18%
  (Rs 1Cr) of the account. That is more careful, not a problem.
- **In a defensive market** at most 2 new ideas are approved and each is at most half size. At Rs 1 lakh half a trade
  (about Rs 12,500) is below the Rs 15,000 minimum, so a defensive day buys nothing until the account is about Rs 3 lakh;
  from Rs 10 lakh it buys 2. With no new trades, nothing is approved at any size.
- **One gap (issue #463):** a strategy's own position count and single-stock cap *replace* the ladder's and are not capped at
  the ladder. The 1% risk size, minimum position, sector rule, cash floor and drawdown halt still apply, so the effect is a looser
  position count and concentration cap, not unlimited risk (below).

## Limits checked

| Rule (settled) | Code (at `7ba3547`) | Observed (test in `test_capital_limits_sizing.py` unless named) | Result |
|---|---|---|---|
| Ladder Rs 10K to Rs 1Cr, scaled with account size | `services/limits.py:127-168` (`RUNGS`), `:181-217` `limits_for` | the four rungs tested (Rs 10K, 1L, 10L, 1Cr) give exactly their published limits; Rs 25K lies strictly between 10K and 1L; the Rs 25L and Rs 50L rungs are covered only by a grid of 40 sizes from Rs 5K up that checks the limits never loosen | Pass |
| Missing or zero account value | `limits.py:188` | smallest rung (2 positions) | Pass |
| 1% risk per trade | `core/config.py:270`; `risk.py:487` | stop-out loss at most 1% of the account for every size and price tested | Pass |
| Rounding never exceeds a limit | `risk.py:518` (`math.floor`) | position value at the signal price is never above the single-stock cap; cash after charges never below zero, also with 2% to 77% cash | Pass |
| Max positions | `risk.py:652,675`; `limits.py` rungs | at Rs 10K, 25K, 1L, 10L, 1Cr (2, 3, 4, 8, 22 positions) the next buy is refused `POSITION_LIMIT`, and with one slot free it is not | Pass |
| Minimum position | `risk.py:831` (`MIN_POSITION`); `limits.py` rungs | below the minimum, refused with a plain reason | Pass |
| 25% per sector; one stock per sector in the smallest tier | `risk.py:751,763`; `limits.py` `sector_rule` | at 1L, 10L, 1Cr a second bank is shrunk to the room left or refused at the cap; sector total never above 25%. At Rs 10K and Rs 25K a second stock in a sector is refused ("one stock per sector") | Pass |
| Cash reserve | `risk.py:816` | at Rs 1L (5%), Rs 10L and Rs 1Cr (10%): refused when buying would dip into the reserve; spends only what is above it. Rs 10K has none | Pass |
| Drawdown halt 15% | `core/config.py:285`; `risk.py:683-691` | value `15%` everywhere it is read (`limits`, `pause_check.HALT`, simulation rules); behaviour tested in #253 | Pass |
| DEFENSIVE 2 new and half size | `brain/modules/m07_risk/allocator.py:62-63,184`; factor also pinned in `test_tv22_reserved_slot.py:110` | at Rs 10L and Rs 1Cr exactly 2 are approved, each at most half the normal size (rounded down); at Rs 1L none (half a trade is under the minimum); NO_NEW_TRADES approves none | Pass |
| Daily buy cap 5 | constants `simulation/rules.py:26`, `brain/portfolio_sim.py:33` | constants only here: the cap is enforced in the simulation ledger (`test_simulation_app_rules.py:63,91`) and `brain/portfolio_sim.py:336`, not in the allocator, and is not re-tested in this file | Constants pinned |
| Brain allocator keeps a running tally | `allocator.py` `allocate` | never more than the free slots, cash or 25% per sector across a batch | Pass |
| Plan +8% / -4% / half out +5% / 15 days (brain); 5D +2% / -4% / 5 | `brain/modules/m08_decide/policy.py:13-18`; `simulation/rules.py` | constants equal the settled values | Pass |
| A strategy's own limits may only tighten | `limits.py:219-226` | tighter values are honoured (control passes). **Looser values replace the ladder** | **GAP** |

## Gap and observations

- **GAP (issue #463; strict xfail, not fixed):** a strategy row's `max_positions` and `capital_allocation` replace the
  ladder's position count and single-stock cap with no cap at the ladder (`services/limits.py:219-226`). Tested with a real
  `Strategy` row. Not affected, and still applied: the 1% risk-per-trade size, the minimum position, the sector rule and cap,
  the cash floor and the drawdown halt (`test_what_a_loosened_override_does_not_loosen_the_other_limits_still_hold`). So the real
  effect is a looser position count and concentration cap; a stop-out still costs at most 1% of the account. The fields are settable
  through the strategy write routes (owner only). Fix suggestion (not applied): take the smaller of the strategy value and the
  ladder value. I did not read production strategy rows, so I do not know whether any existing strategy uses these fields.
- **Observed, not a defect:** caps are measured at the signal price. The paper fill is 5 basis points higher, so a
  position that fills a cap exactly can end up to 0.05% over it (about Rs 50 on Rs 1,00,000). Pinned in
  `test_measured_at_the_fill_price_a_position_can_pass_the_cap_by_the_slippage_only`.
- **Observed:** with no stop given, sizing assumes a 5% stop (`core/config.py:281`), which gives a smaller position than the
  4% plan. More careful.
- **Not verified here:** production's sizing mode. The code default is `risk_based`; if production sets `fixed_amount`
  (`risk.py:471-486`) a flat amount is raised to the minimum position instead. I did not read production settings.

## Hard-coded values (review-risk step 3)

- `RESERVATION_DEFENSIVE_SIZE_FACTOR = 0.5` (`risk.py:293`) repeats the allocator's `defensive_size_factor = 0.5`
  (`allocator.py:62`). Both are 0.5 today; a test pins the allocator's half size.
- `DEFENSIVE_MAX_NEW = 2` and `NORMAL_MAX_NEW = 5` (`brain/portfolio_sim.py:33-34`) and `SETTLED_*` in
  `simulation/rules.py:25-29` repeat settled numbers on purpose; tests pin them to the settled values.
- `brain/pause_check.py:40` `HALT = 0.15` equals `MAX_PORTFOLIO_DRAWDOWN_PCT` (checked in the first test).
- The ladder values in `limits.py` are intended to be literals; `test_each_published_rung_*` pins them.

## Test coverage

New: `tests/test_capital_limits_sizing.py` (see the final run below). Re-run with it on
`swing_trade_ml_dev4b_test`: `test_limits.py`, `test_risk.py`, `test_portfolio_risk_layer.py`, `test_money_risk_limits_exit.py`,
`test_simulation_app_rules.py`, `test_brain_m07_module.py`, `test_tv22_reserved_slot.py`: **247 passed, 3 xfailed** (the gap, parametrised over three account sizes).

Related, from #253: a missing equity snapshot lets the drawdown halt read zero, and a missing safety-state row fails open
(`test_portfolio_risk_layer.py:652`, a deliberate choice). Neither is repeated here.
