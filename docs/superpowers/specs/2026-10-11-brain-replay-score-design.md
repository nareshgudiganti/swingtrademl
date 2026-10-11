# Brain replay-and-score — design

Status: DRAFT for owner review (2026-10-11). No code written.

## Why

The brain has no countable track record: live shadow gives ~5 ideas a day, each needs up to 15 trading
days to resolve, and from 2026-10-04 to 10-09 prod counted 0 (risk-downgrade bug, fix on `develop`).
`brain replay-week` already re-runs the brain as of past days with no look-ahead, but replays are
**never scored** (`m09_learn/scoring.py` grades live nightly runs only, by design). This adds a way to
replay a past window, score every idea against what really happened, and report honestly.

## Goal and success

One command: `swingtrade brain replay-score --from D1 --to D2` (or `--days N`). Output: a JSON file and a
plain-English summary answering:

1. Did the brain's ideas beat chance and beat v1 on the same days?
2. Was the pipeline working (runs finished, ideas recorded, data fresh)?

First run: about one month. Extend to 6–12 months only after the month looks right to the owner.

## Scope rules (settled with owner 2026-10-11)

- **Read-only.** No orders, no change to v1, no writes to live evidence. Replay results never count
  toward the M18 "N of 30" gate and are never written to `brain_decisions.outcome*`.
- Reuses `run_replay_week` (non-live runs) and the pure `m09_learn.outcomes.score()`.
- Must not change `COUNT_BLOCKED_TOWARD_GATE` or any trading/sizing/limit code.

## Design

1. **Replay.** Call `run_replay_week` over the window (brain as of 23:59 IST each trading day).
2. **Collect ideas per day**, two tracks:
   - Track A (signal quality): every TRADE idea, plus ideas with `downgraded_from == "TRADE"` that have
     entry/target/stop levels (risk-blocked).
   - Track B (portfolio): only the TRADE ideas that stayed TRADE.
3. **Score each idea two ways**, reported side by side:
   - *Locked rule*: existing `score()` — entry at decision-day close, +8% / −4% / 15 bars, same-bar touch
     = stop.
   - *Strict*: entry at next trading day's open; a gap through the stop exits at that bar's open (worse
     than −4%); costs and slippage from `services/costs.py`; half out at +5%; unresolved when fewer than
     15 bars exist.
4. **Baselines on the same days and universe**: all eligible stocks; random picks (many repeats, fixed
   seed); v1's picks where recorded. Sector-matched random as a later add.
5. **Report.** One line per idea: date, stock, decision, score, reasons, outcome. Totals per track:
   count, resolved vs still-open, target/stop/timeout rates, average net return, break-even win rate
   (about 33% before costs), by score bucket. Unresolved ideas listed separately, never counted as wins
   or losses.
6. **Limitations block, always printed:** watchlist older than the first `watchlist_snapshots` row uses
   today's list (survivor bias); models trained on later data flatter results (state what M06/M05 were
   trained on, and flag if their training window overlaps the replay); daily candles cannot settle
   exactly which of target/stop came first.

## Units

| Unit | Does | Depends on |
|---|---|---|
| `brain/replay_score.py` | orchestrate replay, collect ideas, produce report dict | `replay_week`, DB read |
| `brain/replay_scoring.py` (pure) | strict scorer; no DB | `outcomes.score`, `costs` |
| `brain/replay_baselines.py` (pure) | random/all-eligible baselines from bars | pandas |
| CLI `replay-score` in `cli.py` | arguments, write JSON + summary | above |

Strict scorer stays pure so it is unit-testable without Docker.

## Testing

- Unit (no DB): gap through stop, same-bar touch, half-out at +5%, 15-bar timeout, fewer than 15 bars
  (unresolved), costs applied.
- Integration (Docker Postgres up, else it hangs): seeded fake candles, replay 3 days, assert ideas
  collected, nothing written to `brain_decisions.outcome*`, Track A ⊇ Track B.
- Run with `backend/.venv/Scripts/python.exe` and the env-unset prefix from CLAUDE.md. Format only
  touched files.

## Open risks to settle during planning

- How far back candles and `watchlist_snapshots` really go on the target DB (local data ended
  2026-09-08; prod is newer). Sets the honest maximum window.
- Whether v1's historical picks are stored in a form the baseline can read.
- Whether replay runs are fast enough for 6–12 months (per-day run time).

## Not in this spec

Full portfolio simulator (cash, positions over time), news/LLM intelligence, changing the 30-idea gate,
promoting calibrated models. Each is a separate later spec.
