# Evidence plan — Amendment 1 (`evidence-defs-v2`)

Status: **APPROVED 2026-10-21 (owner merged PR #37 and confirmed it as the final read). LOCKED: tag
`evidence-defs-v2` is on the commit that adds this line.** Phase B (from
2026-11-09) is judged under it. Owner decisions: section A11. Tracker: Atlas → "Prove the brain is
strong" → ps0c.

Amends: `2026-10-15-evidence-and-pilot-plan.md` (frozen, `evidence-defs-v1`). That plan stays the single
source of truth; this file adds to it and changes nothing already run.

**Rule for this amendment.** It applies only to results produced **after** it is tagged. Every result made
before keeps the version it was made with (`evidence-defs-v1`, `wf-protocol-v1`). No running experiment's
rules change: the forward trial (from 2026-10-14) keeps its rules; only how its results are *shown* is
fixed here (section A4), and that makes it stricter, not looser.

**What a pass means.** Passing every rule is evidence that the brain worked under the tested conditions
and period. It is not a guarantee of future profit, and real money still needs the owner's separate
go-ahead.

Why now: the owner approved the "prove the brain is strong" section (ps1–ps10) and an outside review's
additions on 2026-10-20; Wave 0–2 results arrived the same day (section A9).

---

## A1. Four result labels

Every check in every evidence file ends in exactly one of these:

| Label | Meaning |
|---|---|
| **PASS** | the locked pass rule is met **on data nobody had looked at** (confirmation data, plan section 4) |
| **FAIL** | the locked pass rule is not met. A failure stays on record; a re-run with new rules is a new protocol version |
| **INCONCLUSIVE** | not enough evidence to decide: fewer than 30 trading days with ideas, fewer than the required finished ideas, or the confidence interval spans the line. Never rounded up to PASS |
| **NOT TESTABLE** | our data cannot answer it (for example stocks that disappeared, history of splits and bonuses). Written on every report it affects |

**On development data the best possible label is "NO WARNING (diagnostic)", never PASS.** All local data up
to 2026-09-07 is development data (EXPOSURE-LEDGER.md). A FAIL on development data is a real warning.

The plan's existing words map onto these: "Insufficient evidence" = INCONCLUSIVE; "Not proven" at 9 months
= INCONCLUSIVE (final, and it counts as not passed).

## A2. More comparisons (added to section 3a)

Same rules as every 3a baseline: same decision days, next-open entry, +8% / −4% / half out at +5% / 15
trading days, same costs (`services/costs.py`), same stock list.

| Comparison | Definition | Question it answers |
|---|---|---|
| **Rules-only** | the same brain on the same days with every model score removed (M06 switched off and no model fallback), so ideas come only from the rule modules and the risk gate | does the model add anything over the rules? |
| **Model-only** | the 5 stocks with the highest raw model score each day, with no brain modules (the walk-forward "model best 5") | do the rules add anything over the model? |
| **Risk-matched random** | for each candidate idea, a random stock from the **same sector** and the **same volatility third** (20-day volatility, split into thirds across the day's stock list) on that day; 1,000 seeded draws, seed 7 | is a "win" just picking riskier stocks or a hot sector? |
| **NIFTY 50, matched** | already in 3a | — |
| **Mid / small-cap index, matched** | as NIFTY matched, with the NIFTY Midcap 150 (or Smallcap 250 for small-cap ideas) | **NOT TESTABLE until after the current trial**: we do not store these indices. Owner decided (2026-10-21) to add them **after** the current trial (a data-layer change); until then this comparison is reported as NOT TESTABLE |

Rules-only and Model-only are run at both levels (trade level and the equal-capital portfolio replay).

## A3. Human-selected ideas never count as the brain's

Any stock a person chose — the owner's horizon-experiment picks, personal picks tracked under Real Trading
or My Holdings, tester positions — carries `origin = human`. It is shown in its own section and is
**never** counted in any brain result, baseline or gate. A test proves no brain report includes it.

## A4. Blind trial results stay sealed; safety stays visible

The forward practice trial from 2026-10-14 is Hold-out A.

- Until its planned evaluation, reports show **counts only** for it: ideas, finished, still open, blocked.
  No profit, loss, hit rate, or split by score, market type or sector.
- **Always visible:** run errors, modules dropped, data freshness, halts, risk-rule checks, decision flips,
  fill-quality and reason spot-checks (none of these are trade outcomes).
- Anyone who looks at sealed results early adds an exposure-ledger row, and that stretch becomes
  development data.

**Exposure so far (recorded 2026-10-21).** Trial results were already on display before this rule:

| Where | What was shown | Since |
|---|---|---|
| Observatory "Results this month" card (`GET /brain/observatory/outcomes`, deployed 2026-10-16) | profit, hit rate and comparisons for trial days from 2026-10-14 | about 2026-10-15/16 |
| Daily check record, trial section (stored every day, readable via `/brain/daily-checks`) | hit rate, average result (`avg_net`) and edge over every-stock (`edge_vs_every_stock`) per set | about 2026-10-15/16 |

- Whether anyone actually looked is **UNKNOWN**. It is recorded as UNKNOWN, **not** as clean
  (EXPOSURE-LEDGER.md, Production data).
- Hiding the results from now on does **not** make the trial fully blind again. Earlier exposure is never
  erased from the record.
- The trial itself continues **unchanged** (same rules, same dates).

**Hiding rule — enforced in the backend, not just on screen.** "Sealed" means the server never sends it;
hiding a card on a page is not enough.

| Never contains trial-period results | Stays visible |
|---|---|
| any API response, report, download, evidence pack, daily summary or Telegram message | counts: ideas, finished, still open, blocked |
| ("results" = profit, hit rate, average result, or any comparison with a baseline) | safety checks, operational failures, risk warnings |

- **One switch in one place** controls the seal. Unsealing needs the owner's approval and a recorded
  commit.
- **A test proves it:** it puts a distinctive result (a number that appears nowhere else) on a trial day,
  calls every route, and fails if that number shows up in any response.

## A5. Sample size and uncertainty on every number

Every reported result shows its count (ideas, trading days, folds), its period, and its confidence range
(the 3a method). Fewer than 30 trading days with ideas → INCONCLUSIVE, whatever the average says. Windows
that overlap (for example a long fall containing a shorter one) are named as overlapping and never counted
as separate pieces of evidence.

## A6. Evidence manifest

Every evidence file starts with: protocol id and version, defs version, code commit, data window, stock
list (and its known survivorship), model name and training window, horizon (5, 15 or 30 days), and the
exposure-ledger row it added. A file without a manifest is not evidence.

## A7. Horizons are never mixed

The forward trial is the 15-day rule (+8% / −4%). The 5-day (+2%) v1 bot and the 5- and 30-day research
experiments are separate (owner, 2026-10-20). Every result states its horizon; no table or average combines
horizons.

## A8. Pause rules for the brain (ps7) — two kinds

Built **after** the trial (it changes the stage gate). The numbers are fixed **here, before** anyone looks
at trial outcomes.

**Safety pause** (immediate and automatic; the brain goes back to practice / NO NEW TRADES):

| Trigger | Already caught today? |
|---|---|
| risk gate (M07) did not run | yes — constitution: NO NEW TRADES |
| market data not fresh | yes — constitution |
| market judge (M10) missing and breadth missing | yes — PR #33: NO NEW TRADES |
| a TRADE with an unusable plan reached the final check or approval | yes — PR #33 refuses it; the pause adds "stop the stage" |
| any module dropped in 2 nightly runs in a row | no — new |
| paper / broker reconciliation mismatch | no — new |

**Performance pause** (the brain goes back to practice; owner decides what next). The numbers below are
**PROVISIONAL** (owner, 2026-10-21) until the historical check that follows:

| Trigger | Provisional |
|---|---|
| losing finished ideas in a row | 8 |
| two calendar months below the every-stock baseline (after costs) | yes → pause |
| the brain's own book falls from its peak | 8% (well before the account-wide 15% halt) |

**Historical check before switching on.** Before the performance pause is switched on, replay these
numbers on development (old) data and report:

1. **False alarms:** how often they would pause by bad luck alone — for example, random picks with the
   same hit rate as the brain.
2. **Order with the 15% halt:** that they trigger **before**, and never conflict with, the account-wide
   15% drawdown halt.

The numbers are **never tuned on Phase B or trial results**. Any change is recorded here before the
experiment rules are frozen.

## A9. Results recorded so far (development data — diagnostics, not proof)

| Check | Label | Note |
|---|---|---|
| ps10 look-ahead audit | NO WARNING (diagnostic); 3 NOT TESTABLE | `lookahead-audit-2026-10-20.md`; survivorship, sector map, corporate actions |
| ps3 higher costs | **FAIL (warning)** | already −0.20% a trade at normal costs (2023-07..2025-01); −1.09% at 2× charges and 0.3% worse fills |
| ps2 bad markets | NO WARNING on drawdown (diagnostic); returns mixed | banner roughly halved the worst fall (longest fall −8.9% vs −16.4%) but the brain still lost money in every window; Feb–Mar 2026 return worse with the banner. Windows overlap (A5) |
| ps1 modules on/off | pending | read at portfolio level; switching one module off cannot show interactions; no module is removed during the trial |
| ps8 market type and sector split | reporting only | prod hold-out view = counts only (A4) |

## A9a. Pass-rule definitions (clarifies plan section 4)

These explain the plan's pass rules; they do not loosen any of them.

| # | Term | What it means |
|---|---|---|
| 1 | **"95% confidence"** | The plan's 3a method. Take the brain's edge over every-stock for each day. Re-sample it 2,000 times in blocks of 15 consecutive trading days (a "block bootstrap": it keeps neighbouring days together because they are related), seed 7. The 5th-percentile lower bound of the mean day edge must be **above zero** (one-sided 95%). |
| 2 | **Many tries, one winner** | Phase B tries exactly **3 candidates**, on development data only. Only the **single best survivor** is locked (`wf-protocol-v2`). It must then pass **all** rules together on brand-new confirmation data (Phase C). One candidate, one test, all rules at once — so it is not "try many until one wins". |
| 3 | **"No market type worse than −1% per trade"** | The **real** average result after costs, slippage and price gaps — not the planned risk. Planned risk is −4% a trade, but real losses can be bigger when a price gaps past the stop. |
| 4 | **The pass criteria themselves** | Confirmed by the owner as written in plan section 4 (tracker item ev2). |

See "What a pass means" at the top: passing is evidence for the tested conditions and period, not a
guarantee.

## A10. Not part of this amendment

- **Full decision-chain logging** (model version, input snapshot, feature times for every decision): useful,
  but it adds code to the live brain. Built only after a technical review (speed, data size, rollback, trial
  impact) and the owner's OK.
- **Rebuilding past portfolios** (historical holdings, cash, orders) for replays: the biggest open job;
  needed before ps1/ps2 results can judge the whole brain. Until then those replays are labelled "today's
  portfolio" (a known limit).

## A11. Decisions recorded 2026-10-21

| # | Decision (owner, 2026-10-21) | Where |
|---|---|---|
| 1 | Amendment **approved in principle**, with the clarifications in this file | Status line |
| 2 | Performance-pause numbers (8 losing finished ideas in a row; 2 calendar months below every-stock; brain book 8% fall from peak) are **PROVISIONAL** until the historical-data check | A8 |
| 3 | NIFTY Midcap 150 and Smallcap 250 are added **after** the current trial; until then that comparison is **NOT TESTABLE** | A2 |
| 4 | Trial results are hidden in **both** the Observatory and the daily check, and everywhere else (API, reports, downloads, evidence packs, daily summaries, Telegram). Past exposure is recorded as **UNKNOWN** | A4 |
| 5 | Pass criteria in plan section 4 confirmed as written (ev2), with the definitions in A9a | A9a |

Done 2026-10-21: owner's final read (PR #37 merged), change-log row added to the plan (section 7), tag
`evidence-defs-v2`. The seeded stock split (ev15, PR #41, `docs/brain/evidence/stock_split/`) is locked
with it.
