# Data audit and the honest scoreboard — DRAFT for owner approval (2026-10-26)

Status: **Approved 26 Oct to build S1 and S2 as read-only reports (conditions 1-9); built, results in section 7. No deployment, no change to trading, risk or research rules.** Follows the outside review the
owner pasted on 2026-10-26: pause new 5-day runs, keep the 15D trial frozen, audit first, build an honest scoreboard,
separate model quality from brain decisions, then one narrow hypothesis. The aim is to measure whether the score
deserves trust, not to design a test that makes it look trusted.

Wording rule from the review: the evidence says *this model did not show reliable skill under this protocol*. It does
not say no model can, and it does not say the inputs are the cause.

## 1. Data audit (updated 26 Oct after the owner's conditions)

Dates below are IST trading days. (My first list used UTC dates and was one day early: candles are stamped IST midnight.)

| # | Item | Result | How |
|---|---|---|---|
| 1 | Bad bars (high < low, close outside range, price <= 0, zero volume) | none in 61,838 bars (49 stocks) | read-only SQL |
| 2 | Missing days | no gap over 5 calendar days to Feb 2025 | read-only SQL |
| 3 | Corrections table | empty (0 rows); arrivals table empty | read-only SQL |
| 4 | The three largest one-day moves, checked against published records | **ADANIENT 2023-02-02 (-26.7%)**: matches press reports of a 26.5% close-to-close fall (BSE Rs 1,564.70; ours is the NSE close, 1,517.5). **ADANIENT 2023-02-01 (-28.2%)**: consistent with the FPO-withdrawal day and a headline "recovers after falling 35%", but I did not obtain a source quoting that day's close, so this one is only partly verified. **INDUSINDBK 2025-03-11 (-27.2%)**: matches the reported 27.17% fall to Rs 655.95 after the derivatives-accounting disclosure; ours 656.0. All three are real events on heavy volume (3x to 14x normal), not price-basis changes | read-only SQL + press reports |
| 5 | Could a split or bonus hide in a smaller move? | A split or bonus need not give -50% (the reviewer is right). Checked: every move beyond +-12% in the 49 stocks (36 days) lines up with a known event: the 2024-06-04 election-result day (PSU and Adani stocks), the Jan-Feb 2023 Adani sequence, the 2024-11-21 Adani indictment news, INDUSINDBK results, the ONGC windfall tax. Drops of 5-12% on quiet volume (under 1.3x normal) fall on market-wide down days (several stocks the same day), not on single stocks. **Known split cross-check:** BAJAJFINSV had a 1:5 split plus 1:1 bonus (combined factor 10, ex-date 2022-09-13, NSE circular). Our series is continuous through it (1,713.8 to 1,784.8, +4.1%) and the Feb 2022 level is about a tenth of the market price then, so that history is back-adjusted | read-only SQL + published split notice |
| 6 | Splits and bonuses versus demergers | The **wider 306-stock data is not adjusted for demergers** (audit F-07: VEDL -33% on 2026-04-30). Splits and bonuses appear adjusted (BAJAJFINSV). I found no unadjusted event in the 49, but I have no authoritative corporate-action list to prove it; this stays a stated limit | AUDIT-2026-10-13 F-07 |
| 7 | Look-ahead in inputs and labels | PASS for rows 1-11 of the 20 Oct audit; training keeps only rows whose label window ended by the fold cutoff | `docs/brain/evidence/lookahead-audit-2026-10-20.md` |
| 8 | Signal timing and entry price | **Resolved by reading the code.** The score is from the decision day's close (`score_series`); the entry is the next trading day's open (`replay_scoring.after_day` takes bars strictly after the decision day; `strict_score` fills at the first of them, with slippage); target, stop and half-out are measured from the fill. S1 and S2 use exactly this | code read |
| 9 | Train/test overlap | **Resolved by reading the code.** Each fold's cutoff is the day before the fold starts (`make_folds`); training keeps rows whose label window ended by the cutoff (`apply_cutoff`); the S1 integrity check found no fold with a missing or late cutoff and no duplicate stock-days. A trade decided near a fold's end can run into the next fold's dates; that is fine because nothing was trained after the cutoff | code read + S1 integrity |
| 10 | Conflicting scores in the UI (KEI 95 vs 91, and others) | **Explained by model, horizon and run, not by picking one.** For KEI the stored data holds several numbers that look alike: v1 `ml_swing_midcap` 76.3% (a 5-day endpoint model, 2026-10-09), v1 `ml_swing_midcap_barrier` 59.5% (a 15-day barrier model, 2026-10-16), and the brain's 15-day `model` score 89.2% (2026-10-05 morning) and 91.9% (2026-10-06), while a later 2026-10-05 afternoon run stored no score. They differ in model, horizon, score type (`score_source`: model or combined) and run time. **Gap:** brain decisions store `score_source` and run time but not the model version id, so a displayed brain score cannot yet be tied to a model file from the database alone. Nothing was built (UI wording is the owner's call). Rule for any card: show model name, horizon and run time next to every score, and never compare scores across them | read-only SQL + code |
| 11 | Are the 129 reject stocks a clean test set? | **Not established.** They are a seeded random half of the 257 stocks outside the 49 (seed 7), not stocks chosen for any quality, so "reject" names their role only. They were exposed to price-movement classification (F-07, no rule changed) but, per the exposure ledger, to no trading result. Not clean in three ways: (a) the 257 include small and thinly traded names unlike the 20-30 stocks the owner may trade; (b) their prices are unadjusted for demergers (F-07); (c) 3 symbols lack current prices (ev10). Use only as a reject-only robustness check, as Phase B already says | ledger, ev15, F-07, ev10 |
| 12 | Costs | our numbers equal or slightly above Zerodha's published delivery charges (17 Oct check); slippage 5 bps per leg; round trip about 0.36% | `COSTS-CHECK-2026-10.md` |
| 13 | Known limits | survivorship (today's 49 stocks), today's sector map for every past day, no corporate-action table, demergers unadjusted in the wider data | audit rows 12-14 |

Finding that changes the review's suggested first hypothesis: **market breadth, sector-relative strength, India VIX and
NIFTY-relative strength are already model inputs** (`ml/features.py`). So "add breadth and sector strength" is not a
new input group.

## 2. What already exists (do not rebuild)

- `brain/ranking_diagnostics.py` (15D, development data 2025-02-01 to 2026-08-15, never the protected sample). Its
  26 Oct-readable results: rank correlation between score and result is +0.011 (lower bound −0.015), so the score ranks
  stocks on a day about as well as chance; best-5 −0.14%, middle-5 −0.40%, worst-5 −0.75% per trade; random 5 −0.28%;
  scores 0.80–1.00 averaged +0.62% over 885 ideas in 12 folds (all other bands negative). The fifth-by-fifth table is
  not monotone (top fifth −0.23%, bottom fifth −0.50%).
- `brain/score_evidence.py` and `score_reliability`: what a score band meant.
- Phase B (from 9 Nov) already tests the one visible signal as a pre-set candidate B1: *only ideas with score ≥ 0.80*.
  This is a hypothesis fixed in advance, run once, with the reject set used only to reject.

## 3. Scoreboard S1 — model quality (all ranked ideas, no account limits)

For each trading day in a stated period, rank the eligible stocks by score and compare four groups: **Top 5, next 5,
next 5, and all eligible stocks** (the benchmark).

Fixed rules (same for all groups and all periods): entry at the next open; the horizon's own target and stop; the
horizon's own time exit; equal hypothetical ₹1,00,000 per idea; the repo's cost model and 0.10% slippage per side.

Per group it shows: ideas given, finished ideas, up/down counts (target hit, stop hit, time exit), average result after
costs, and the gap to the benchmark with an honest uncertainty range. **Open ideas are shown separately and never mixed
with finished ones.** Every table carries the horizon label (5D / 10D / 15D) and the period.

Periods:
- development data (2025-02 onward, not the protected sample) for the 15D label — mostly already produced by
  `ranking_diagnostics`; S1 adds the next-5 groups and the plain layout;
- the frozen forward trial days: **counts only** until the trial's evaluation (trial seal, Amendment 1 A4). No result
  numbers for trial days are shown before then.

## 4. Scoreboard S2 — brain decisions apart from model quality

1. First S1, with account limits ignored: this answers "is the score good?" and does not depend on money available.
2. Then, separately: brain-**approved** vs **blocked** ideas, with the rejection reason (money limit, cool-down,
   results-day, exchange list, and so on) and the same result columns. Account capacity must never decide which stocks
   enter S1.
3. Trial-day figures are counts only (sealed). Development-period replays can show results.

## 5. Hypothesis (after the audit and S1 — not before)

- One primary horizon: **15D**, because it has the frozen trial and Phase B. 5D and 10D are secondary checks with rules
  fixed beforehand, or are left alone.
- Candidate hypotheses (one at a time, each with its pass rule written first):
  - H-a: *Only very high scores carry information* — already Phase B B1; wait for its result.
  - H-b: a new input group with **reliable publication timestamps** (company results, announcements) — see the Company
    and news tab design (Atlas cn). Adding news or results without timestamps can leak the future.
  - H-c: a feature-importance or ablation look at the existing inputs to see which, if any, carry signal (no new data).
- No hypothesis is tested before the owner approves its written rule and its test data.

## 6. Order of work and approvals

1. Finish audit items 8–11 (read code, list score displays, check the reject set). Read-only. **Needs no approval.**
2. Build S1 as a read-only report on development data. **Owner approves this spec first.**
3. Build S2 on the same data (and counts-only for trial days).
4. Review S1/S2 together, then draft one hypothesis and wait for approval.

Frozen files are not touched: S1/S2 are new read-only modules next to `ranking_diagnostics`; the 15D trial and the seal
stay as they are.

## 7. Results of the first runs (26 Oct) and what limits them

Reports (generated, read-only, local development database): `docs/brain/evidence/scoreboard/`.

**S1 (development data, 2025-02-01 to 2026-08-15, 20 folds, 379 days, 49 stocks, 18,565 ideas, all finished):**

| Group | Ideas | Average net per idea | Gap to all eligible (per day) | Lower bound |
|---|---|---|---|---|
| Top 5 | 1,895 | -0.14% | +0.14% | -0.09% |
| Ranks 6-10 | 1,895 | -0.32% | -0.05% | -0.25% |
| Ranks 11-15 | 1,895 | -0.41% | -0.14% | -0.29% |
| Ranks 16-20 | 1,895 | -0.20% | +0.07% | -0.05% |
| All eligible | 18,565 | -0.27% | 0 | n/a |

Reading: the Top 5 did a little better than the average stock, but the lower bound is below zero, so the edge cannot be
told apart from luck on this data, and the groups do not fall steadily with rank (ranks 16-20 beat ranks 6-15). Top 5
beat all eligible stocks in 11 of 20 folds. This matches the earlier ranking diagnostic (best 5 -0.14%, all -0.27%).
It changes nothing: Phase B and B1 (score >= 0.80) are untouched.

**S2 (stored brain ideas, local database, 2026-07-13 to 2026-10-31):** 561 blocked ideas (strict 15-day rule: 106 target,
317 stop, 138 time limit, average -0.99%) and **0 approved ideas**. Every blocked idea carries the reason "risk check used
today's account", which is a property of replays (they read today's account, not the replayed day's), not a finding about
the brain. So S2 cannot say anything yet about approved ideas; the point-in-time replay (ps12) is the way to get
approved ideas, and it does not store per-idea lists. No sealed (trial) day produced any count in this local database;
prod's trial counts stay counts-only.

**Limitations to keep on every reading:**
1. Local development database only; not production, not the trial.
2. S1 trains its own fold models (as wf-protocol-v1 does), so it measures "a model like the brain's", not the exact
   brain score stored on a given day.
3. Survivorship, today's sector map, no corporate-action table, unadjusted demergers in the wider data.
4. S2 approved-versus-blocked is descriptive: different stocks, different days, and replays block everything.
5. Brain decisions do not store the model version (item 10).
