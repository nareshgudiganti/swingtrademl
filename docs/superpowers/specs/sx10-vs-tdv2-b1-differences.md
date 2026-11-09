# SX10 versus the unsigned td-protocol-v2 draft's B1: exact differences

Status: **comparison note only.** No combination of the two is proposed, no result of one is to be reused for the other,
and the td-protocol-v2 draft (branch `change/td-protocol-v2-draft`, file `2026-11-03-td-protocol-v2-DRAFT.md`) is not
changed. Both documents are unsigned drafts. Nothing is signed, tagged, trained or activated.

Labels: **VERIFIED** = read in the two draft files this session (the td-v2 draft with `git show`); **PROPOSED** = what a
draft proposes (not agreed); **UNVERIFIED** = not checked. Whatever the td-v2 draft says about its own inputs is PROPOSED
by that draft and unbuilt.

Owner decisibefore signing: SX10 and td-v2 B1 stay SEPARATE protocols; their exact differences are documented here before any
combination is even proposed. This note proposes none.

## Differences

| Item | SX10 (`sx10-research-protocol-superseded.md`) | td-v2 B1 (`2026-11-03-td-protocol-v2-DRAFT.md`) |
|---|---|---|
| **Question** | Does adding three official-sector-index inputs to the 53 existing inputs help rank the 47 mapped large stocks, compared with the 53 alone (arm C_56 versus A_53), on identical rows and folds? (VERIFIED) | Does adding breadth and sector strength (8 new inputs) help rank the 49 large stocks, judged by absolute results against benchmarks? (VERIFIED) |
| **Label** | Barrier: +6% before -3.5% within 10 trading bars (`ml/features.build_label`; `ten_day.TARGET/STOP/HORIZON_BARS`). Tested equal to the `ten_day` definition in code. (VERIFIED) | Barrier: reaches +6% before -3.5% within 10 trading days, "as in v1". Same words; **unbuilt**, so equality with SX10's tested label is UNVERIFIED. (VERIFIED text, UNVERIFIED equality) |
| **Trade rule judged** | td-v1 trade, via `ten_day.score_trade`; reported beside the ranking result, descriptive (PROPOSED) | Same trade (next open, +6%/-3.5%, close of day 10, top 5, no repeats), and it is a pass row (PROPOSED) |
| **Existing inputs** | The 53 (`FEATURE_COLUMNS`) as the primary baseline; arm R_37 = model 2's 37 as a separate reference (owner decision before signing) | "The 37-46 existing price-and-volume inputs the production-style 10D model already uses" (so 37 or 46; not the 53) |
| **New inputs** | 3: `sector_ret_10d_vs_nifty`, `sector_rank_10d`, `stock_vs_sector_10d` (equals B1-5, B1-7 and B1-8 in concept; B1-6, the 20-day version, was dropped before signing because it is the difference of two existing inputs) | 8: B1-1 breadth above 50-day average, B1-2 breadth above 20-day average, B1-3 advancers share, B1-4 new-highs share, plus B1-5 to B1-8 (sector return 10d and 20d minus NIFTY, sector rank, stock minus sector) |
| **How "sector" is defined** | The stock's official NSE sector index from `ml/sector_map.py`; rank among 15 sector indices (`include_unverified=False`) | Equal-weight mean of the stocks of the sector inside the universe (the stock's existing sector label); not an official index. Whether a reliable sector label exists for all 49 is untested in that draft. |
| **Breadth** | None new. (The 53 already hold `breadth_pct_above_sma50` and `breadth_advance_pct`, built from today's watchlist.) | 4 new breadth inputs over a "dated universe" with point-in-time membership, or a with/without-breadth diagnostic (section 3.2) |
| **Number of inputs in the challenger** | 56 (53 + 3; renamed from C_57 before signing) | 45 to 54 (37 or 46 existing + 8) |
| **Sector overlap with existing inputs** | Measured on real data (see the SX10 draft section 4): the one input that was a difference of two existing inputs was dropped; the other three partly overlap | The draft says nothing about overlap; B1-5 to B1-8 are subject to the same concept overlap (UNVERIFIED, not measured) |
| **Universe** | 47 of the 49 model stocks (ASIANPAINT, BHARTIARTL have no verified official sector index; owner decision) | The 49 model stocks, frozen at the lock date; breadth over the 306 local stocks |
| **Time / folds** | Retrospective walk-forward: 34 chronological 28-day test folds 2023-07-01 to 2026-01-31 plus a holdout 2026-02-01 to 2026-08-15 scored once; expanding window, label-purged, embargo 10 sessions (PROPOSED, harness built) | No walk-forward folds. Train on all history to the lock date, freeze, then judge **forward only** in a shadow lane (about 6 months, month 3 counts only, hard stop month 9). Routes E1/E2/E3 undecided. |
| **Evidence class** | History already looked at; a pass only means "worth proposing a forward shadow test" (PROPOSED) | Forward, independent evidence; the old 2023-07..2025-01 window "may never be the pass-or-fail sample" |
| **Evaluation / pass rule** | Paired and ranking-based: C_56 beats A_53 on top-5 excess over every eligible stock in at least 60% of eligible folds, lower bound of the paired daily difference above zero (block 10, 2,000 draws, seed 7), at least 12 eligible folds and 100 ideas, holdout same sign, no-harm descriptive (rows R0 to R5, PROPOSED) | Absolute against benchmarks: beats every stock and random-5 in 60% of eligible months (at least 4), bootstrap lower bound above zero, positive average after costs, beats NIFTY 50 after costs, 15% drawdown halt and 50%-of-profit month limit, 100 finished ideas, market-type floor -0.25% per trade (PROPOSED) |
| **Comparator** | The same model without the three inputs (A_53), and the production-reference configuration (R_37), on identical rows | Every stock, 200 random-5 accounts, NIFTY 50 held, cash, 5 strongest 20-day risers |
| **Costs** | Net result via `ten_day.score_trade` (0.10% slippage per side, charges on its Rs 40,000 position), descriptive; the ranking metric decides | Same scorer; net profit is a pass row |
| **Model recipe** | Pinned LightGBM recipe of the drafts (seed 42, from `ml/train` defaults); the `fit_fn` is injected | Not specified in the draft ("production-style 10D model") |
| **Seed / determinism** | seed 42, `n_jobs=1` for the research run (PROPOSED) | not stated |
| **Status** | DRAFT, unsigned, untagged; draft PR #148; harness and label support built and tested with stubs; no real-data fit | DRAFT, unsigned, untagged; nothing built; waits for decisions D1 to D8 |
| **Budget / multiple testing** | One pre-registered paired comparison; counted with SX5 and the others in the programme (SX10 draft section 8) | "The 7th experimental candidate" in the programme (td-v2 draft section 11); owner decision D2 pending |
| **If both were signed** | The SX10 draft notes the same idea would be counted twice (B1-5, B1-7 and B1-8 equal its three inputs; B1-6 was dropped from SX10 as redundant) and that B1 should then be re-scoped or retired; **that is the owner's decision (SX10 A5) and is not made here** | Unchanged by this note |

## What this note does and does not say

- No combination of SX10 and B1 is proposed. They remain two separate protocols with separate pass rules, separate
  rows, separate evidence classes and separate hashes.
- No SX10 result may be reported as a B1 result, or the reverse. If B1 is later re-scoped, that is a new, written owner
  decision on its own draft.
- The td-v2 draft is not edited by this work. Differences marked UNVERIFIED depend on that draft being built.
