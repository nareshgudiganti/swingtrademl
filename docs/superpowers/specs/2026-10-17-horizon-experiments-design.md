# Independent horizon experiments (5 and 30 trading days), design revision 3

**Status:** for owner review. Nothing is built. No push, merge, deploy or change to existing trading behaviour without separate approval.

**Owner decisions (17 Oct):**
- Keep the 15-day brain trial untouched.
- Add 5-day and 30-day research experiments beside it.
- Simulated only: no real or bot paper orders.
- 30 days is a documented research-only exception to CLAUDE.md principle 7.
- An owner-selected experiment never validates an AI model.
- Compare on returns after costs, drawdown and benchmarks, not on win rate.

## 1. What already exists (checked in code, `main` 4f3cc19)

| Need | Existing piece | Use |
|---|---|---|
| NSE holidays | `core/holidays.py` (`NSE_HOLIDAYS` by year); `core/market_session.py` warns when a year is missing | Session counting. Refuse to schedule into a year that has no holiday list |
| Daily prices | `candles` (daily, stamped IST midnight) | Entry open, exit close, mark-to-market |
| Costs | `services/costs.py::compute_charges(turnover, side)` | The same charges as paper trading. Known limit: the owner believes the cost model overstates Zerodha delivery brokerage. It is frozen as-is in protocol v1 and disclosed |
| Index | `BENCHMARK_INDEX_SYMBOL = "NIFTY 50"` candles | Index benchmark |
| Corporate actions | `services/split_check.py` flags one-day moves over 30% on known ex-dates. There is no adjusted-price table | Flag the outcome; never score it silently |
| Owner-only access | `api/deps.require_owner` | Guards all experiment routes |

## 2. Check of the 20 requirements

All 20 are accepted. Five need a concrete rule, proposed here and frozen in protocol v1 once approved.

- **(2) Paired comparison vs. separate stocks per horizon.**
  - A selection is recorded once and is **scored at both 5 and 30 days**.
  - The owner's "intended horizon" is stored as a label, so "picks meant for 5 days" can still be reported on their own.
- **(5) Timing.**
  - **Cutoff 09:00 IST.** A pick saved before 09:00 on a trading day enters at that session's open. A pick saved after 09:00 enters at the next session's open.
  - **Counting.** The entry session is session 1. The 5-day exit is the close of session 5; the 30-day exit is the close of session 30.
  - Weekends and NSE holidays are skipped.
- **(7) Duplicates.**
  - One active selection per (stock, source) until its longest horizon (30 sessions) has closed.
  - A second pick of the same stock inside that window is refused with a reason, and is kept in the record as rejected.
- **(9) Portfolio drawdown.**
  - Built as a separate stage (P2): simulated cash, equal-weight allocation, a maximum number of positions, and mark-to-market.
  - Fixed-notional outcomes (P1) come first and never claim a drawdown.
- **(10) Slippage.**
  - Prices are daily candles only, so slippage is an assumption: proposed 0.10% per side, frozen in protocol v1.
  - Reports add a sensitivity line at 0% and at 0.25%.

## 3. Schema

New tables only, with no foreign key to any money table.

```
experiment_protocols        one row per frozen protocol version (never edited)
  id, code ('horizon-v1'), frozen_at, created_by,
  horizons int[] (5, 30), entry_rule ('open_of_session_1'), cutoff_ist ('09:00'),
  exit_rule ('time_only_close_of_session_n'), notional_inr, slippage_bps,
  cost_model ('services.costs.compute_charges@<git sha>'),
  universe ('candles-covered NSE equities'),
  benchmarks text[] ('NIFTY 50', 'equal_weight_universe', 'same_stock_buy_hold'),
  dedupe_rule, notes

experiment_cohorts          who chooses the stocks
  id, protocol_id, source ('owner' | 'model'), name, created_at, status ('active' | 'closed')
  -- 'model' rows are allowed by the schema; no model flow is built yet

experiment_selections       APPEND-ONLY (UPDATE and DELETE refused by a database trigger)
  id, cohort_id, instrument_id, symbol_at_entry, intended_horizon (5 | 30 | null), note,
  submitted_at (timestamptz), submitted_by, entry_session (date),
  status ('accepted' | 'rejected'), reject_reason,
  supersedes_id  -- a correction is a new row pointing at the row it replaces;
                 -- allowed only before the cutoff

experiment_outcomes         one row per (selection, horizon, protocol); written by the scorer
  id, selection_id, horizon, protocol_id,
  state ('pending' | 'open' | 'closed' | 'data_issue' | 'void'),
  entry_price, exit_session, exit_price, gross_return, costs_inr, slippage_inr, net_return,
  nifty_return, universe_return, buy_hold_return, excess_vs_nifty, excess_vs_universe,
  data_flags jsonb (missing_bar, stale, big_gap, corporate_action, holiday_calendar_missing),
  scored_at, scorer_version
  UNIQUE (selection_id, horizon, protocol_id)

experiment_job_runs         audit of every scorer run
  id, started_at, finished_at, status, rows_scored, rows_flagged, error
```

The migration is one new revision holding only these tables. It has no link to orders, positions, trades, signals or brain tables.

## 4. Workflows

1. **Submit (owner only).**
   - Through a form on the 5-day and 30-day horizon tabs, or one API call.
   - The server checks that the stock has daily prices, that it is not a duplicate, and that the requested session's cutoff has not passed.
   - It stores the row with a timestamp and returns the entry session.
2. **Correct.**
   - Before the cutoff, the owner submits a correcting row that supersedes the old one.
   - After the cutoff nothing can change, and the original stays visible.
3. **Score (nightly, after the candles job).** For every pending or open outcome, the scorer:
   - reads the candles and fills the entry at session 1's open;
   - marks open picks to market and closes them at session N's close;
   - computes costs, slippage and the three benchmarks, and sets data flags.

   Each row is an upsert keyed on (selection, horizon, protocol), so a re-run gives the same result.
4. **Report.** Per horizon and per cohort, the report shows:
   - the number of picks;
   - independent samples (picks whose holding periods don't overlap, and distinct entry dates);
   - the period covered;
   - mean and median net return, and return per day held;
   - excess return against each benchmark;
   - a bootstrap 90% range;
   - a count of data-quality issues.

   Win rate appears only beside these figures. The label is always "Research, owner-selected, unproven". Nothing is ever labelled validated automatically.

## 5. Isolation and safety

- **No code path to money or the brain.** The experiment package never reaches orders, positions, brokers, risk, the brain or the trial. A test fails if it imports any of them.
- **The scorer is its own scheduled job:**
  - a Postgres advisory lock stops two copies running at once;
  - it has a time limit and works in small batches;
  - it catches its own errors, records a failure in `experiment_job_runs`, and never raises into the brain or bot jobs.
- **It runs after the brain's nightly run and the candles job**, so it never competes with them.
- **The v1 bot (+2% / 5 days) is not changed.** It is shown separately as "v1 bot".
- **The Phase 3a labels stay.** The 5-day and 30-day tabs still say "No supported trading strategy" for trading, and add a separate "Research experiment" section.

## 6. Stages, and what needs B1/B2

| Stage | Content | Needs B1/B2? |
|---|---|---|
| P0 (now) | Record Monday's picks in a dated, append-only list before any code ships. They are scored later from candles | No |
| P1 | Tables, submit and correct API, a scorer with fixed-notional outcomes, benchmarks, a report API | **No.** Only the migration order has to be coordinated with B1 (see below) |
| P1 UI | Research section on the 5-day and 30-day horizon tabs, and the owner's form | No, but needs Phase 3a merged |
| P2 | A simulated portfolio per cohort: cash, equal weight, maximum positions, mark-to-market equity, drawdown | No |
| P3 | Model-selected cohorts | No, but needs its own approval and a frozen model protocol |
| Later | Turning an experiment into a real paper book with its own money and orders; experiments owned by other users | **Yes, B1/B2** |

**Migration coordination.** These tables don't touch B1's tables, so only the order matters:
- If B1 merges first, this revision is re-pointed to follow it before merging.
- If this merges first, B1 re-points instead.
- Either way, a check that there is exactly one migration head runs before merge.

## 7. Test matrix

| Area | Tests |
|---|---|
| Timing | Cutoff before and after 09:00. A Friday pick enters on Monday. A holiday inside the window. A holding window that crosses a year end. A year with no holiday list refuses to schedule |
| Session counting | 5 and 30 are counted from session 1; the exit is at the close of session N |
| Append-only | The database refuses UPDATE and DELETE on selections. A correction before the cutoff creates a new row; after the cutoff it is refused |
| Duplicates | The same stock and source within 30 sessions is refused and recorded as rejected; it is allowed afterwards |
| Scoring | Gross and net return with known prices. Costs come from `compute_charges`. Slippage is applied on both sides. An idempotent re-run gives identical rows |
| Benchmarks | NIFTY, the equal-weight universe and same-stock buy-and-hold, all over identical sessions |
| Data quality | A missing bar, stale data, a gap over 30%, or a corporate-action date marks the outcome `data_issue`; it is never scored silently |
| Concurrency | With two scorer runs at once, the second exits on the lock. A crash mid-run followed by a re-run completes correctly |
| Isolation | The experiment package imports none of orders, positions, brokers, risk or the brain. Bot cash, positions and brain figures are byte-identical before and after scoring (a golden test, like the Phase 2 audit test) |
| Permissions | Every experiment route refuses non-owners and callers with no credentials (added to the existing route walk) |
| Reporting | Independent-sample count with overlapping picks; the bootstrap range; never a "validated" label |
| UI | Owner form, rejection messages, research section on the 5-day and 30-day tabs, nothing shown to non-owners, phone layout |

## 8. Acceptance

- The owner's picks are stored append-only with timestamps. Corrections are visible, and duplicates are refused with a reason.
- Every closed pick has a net return after costs and slippage, plus its three benchmark returns over the same sessions, or a data flag explaining why not.
- Reports show sample size, independent samples, the period, uncertainty and data issues. Nothing is labelled validated.
- The 15-day trial, the bot's money and positions, the brain and the v1 bot are unchanged (golden tests).
- Re-running the scorer changes nothing, and two scorers never run at once.
- The full test suite, the permission walk and the browser checks pass, and an independent review is done.

## 9. Owner decisions still needed

1. **Money per pick** (proposed ₹1,00,000) and **slippage** (proposed 0.10% per side).
2. **Cutoff time** (proposed 09:00 IST) and the duplicate rule in section 2.
3. **Review date and minimum sample.** Proposed: no verdict before 30 independent samples per horizon, and not before 31 Dec 2026. Too few samples means "not proven".
4. **CLAUDE.md research exception** for 30 days, limited to the experiment ledger.
5. **P2 portfolio rules:** starting cash and maximum positions per cohort.
