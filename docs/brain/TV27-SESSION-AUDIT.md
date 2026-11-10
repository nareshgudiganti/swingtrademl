# tv27: trial session count against the NSE calendar (read-only audit, 2026-11-10)

Status: AUDIT AND PROPOSAL ONLY. Nothing here changes the trial, its records or its counters. The code on this branch is a
proposal and must not be merged without the owner's separate written approval (see "Decisions needed").

Written for the owner. Plain English first, detail below.

## The short answer

The trial journal shows **20 sessions**. From 14 Oct to 9 Nov there were only **18 real NSE trading days**. The two extra
"sessions" are market holidays on which the nightly brain run still ran and re-decided on the previous day's prices:

| Day | What it was | Counted today? |
|---|---|---|
| Tue 20 Oct 2026 | Dussehra (market closed) | yes (wrongly) |
| Sun 8 Nov 2026 | Diwali Muhurat: a special Sunday session (afternoon, one-off) | no (no nightly run on a Sunday) |
| Tue 10 Nov 2026 | Diwali Balipratipada (market closed) | yes (wrongly) |

No result is exposed and no order is affected. The trial is still sealed (counts only).

## How this was checked (all read-only)

1. `GET /brain/daily-checks` on production: dates and status only. 18 records, one per real trading day, none on 20 Oct, 8 Nov or 10 Nov
   (the daily check already skips holidays).
2. `GET /brain/trial-journal?from=2026-10-14&to=2026-11-10`: the sealed journal, counts only. It reports `sessions: 20`, first day
   14 Oct, last day 10 Nov, and its day list contains 20 Oct and 10 Nov.
3. `GET /brain/stage`: stage `shadow`, finished 0 of 30, blocked ideas recorded 893 (blocked ideas are never counted).
4. The repo calendar `backend/src/swing_trade_ml/core/holidays.py` (20 Oct and 10 Nov are listed) and
   `trial_journal.load_sessions`, which counts every day with a finished live nightly run and never checks the calendar.
5. A web check of the 2026 calendar (see "Calendar source" below).

## Cause

`trial_journal.load_sessions` takes every day that has a finished live nightly brain run. The nightly job runs on holidays too, so a holiday
run is counted as a session. On those days the brain sees the same prices as the day before, so the extra run adds no new information.
(On 20 Oct the run re-decided 64 TRADE ideas on 19 Oct's prices, all blocked; 10 Nov looks the same: its idea counts are close to 9 Nov's.)

## Impact

| Item | Today | With the proposal |
|---|---|---|
| Sessions shown | 20 | 18 |
| 15-session minimum reached | 3 Nov (counting 20 Oct) | 4 Nov |
| Gate word | too early | too early (unchanged: finished ideas are 0 of 30) |
| Stage (shadow to approval) | needs 30 finished ideas | unchanged (does not use sessions) |
| Finished ideas counted | 0 | 0 |
| Orders, sizing, stops, scores | unchanged | unchanged |

So the error is one day early on a minimum that is not the binding condition. The binding condition is 30 finished brain TRADE ideas, which
is 0 today. Every future holiday would add one more false session (24 Nov, 25 Dec, and any special session on a weekend).

Other readers of `load_sessions` that would change in the same way: the portfolio simulation, the prediction reliability report and the
trial journal API. All three want real sessions only.

## Calendar source (honest limits)

- The repo list says it was "compiled from public NSE holiday calendars ... not the official circular".
- Several broker and news sites agree that Diwali Muhurat 2026 is a special session on Sunday 8 Nov 2026 (afternoon, NSE circular dated
  19 Oct 2026) and that 10 Nov is the Diwali Balipratipada holiday. **These are third-party pages; I could not open the NSE circular
  itself.** Before the owner relies on the dates, open the NSE holiday page and the Muhurat circular and compare.
- The code has no notion of a special session. A special session on a weekend is excluded today only because weekends are excluded.
  A special session on a weekday that is also a holiday (none known for 2026) would also be excluded by the holiday list.

## Proposed exclusion logic (on this branch, not for merge)

`trial_journal.split_session_days(days, trading_days_only=True)` returns `(counted, excluded)`: a day counts only if it is a weekday and
not in the NSE holiday list (`core.market_session.is_trading_day`). `load_sessions` uses it, so excluded days never become sessions.
`trading_days_only=False` restores today's behaviour exactly. The brain's nightly run itself is NOT changed (it is a frozen file).

Tests added (`backend/tests/test_brain_trial_journal.py`):
- the 20 real production run days give 18 counted and exactly 20 Oct and 10 Nov excluded;
- a Saturday and the Sunday 8 Nov Muhurat session are excluded;
- switching the rule off keeps all 20 days as before;
- the gate stays "too early" at both 18 and 20 sessions while no idea has finished.

Test evidence: 46 passed (trial journal, trial journal API, trial freeze, trial seal leaks, and the four new tests), run against the
dedicated local test database. `trial_journal.py` is not on the trial-freeze list, so the freeze test does not need a new approval,
but the session count is a counter the owner said not to change without written approval.

## Decisions needed (written approval required before any merge)

- **D1.** Exclude market holidays from the trial session count (18 instead of 20)? Recommended: yes.
- **D2.** Exclude special sessions such as Muhurat from the count? Recommended: yes (a shortened one-off session is not comparable).
- **D3.** Apply the correction to the days already counted (so 20 Oct and 10 Nov drop out of the displayed count)? Recommended: yes,
  with a note in the exposure ledger that these two days were excluded and why.
- **D4.** Also stop the nightly brain run on holidays? That edits a frozen file and needs `scripts/approve_trial_change.py`.
  Recommended: no for now; D1 to D3 already make the count right.
- **D5.** Verify the calendar against the official NSE circulars before the change is merged (owner or a reviewer).

Until D1 to D3 are approved in writing, nothing on `main` changes.
