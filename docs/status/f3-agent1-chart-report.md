# F3 agent 1: chart fixes on PR #520 (#240)

Branch fix/240-chart-states-v2, replaces #509. Times IST (25 Nov 2026).

## Checks
- `npx tsc --noEmit -p .` in frontend: no errors.
- `npx vitest run` (full suite): 97 files passed, 1312 tests passed, 0 failed.

## Restored (adapted to main, not copied)
- New `frontend/src/trademind/chartStates.test.tsx` (recharts replaced by plain stand-ins, because recharts cannot size itself without a browser):
  - GlowArea with a missing point emits one `data-testid="missing-day"` ReferenceLine at that day and shows `MISSING_DAY_NOTE` (`missing-day-note`).
  - GlowArea with no missing point draws no marker and no note.
  - Candles zero-volume guard: no NaN/Infinity, volume bar has height 0; a quiet day next to a busy day keeps the busy bar's height.
  - Empty bars: documents current behaviour (renders an empty string: no message, no svg).
- `verify240.test.tsx`: c1b (zero volume) now also asserts the candle itself is drawn.

## Deliberately not restored
- The "No price history to draw yet." message in Candles: the owner has not decided. The empty-bars test above makes the open decision visible; change it with the decision.
- #509's verify240 b1/b2 tests ("Closing price on 30 Nov 2026", `lastDate` prop): they test a stockParts/StockDetail change that is not in #520 and those files belong to another agent. On main b1 stays `it.fails` and b2 passes as written.
- #509's header comment edit in verify240 ("gaps fixed"): not true on main while b1 is still a gap.

## Limits of the new tests
The marker tests prove ui.tsx passes a ReferenceLine per missing day and prints the note. They do not prove recharts draws the line in a real browser (no browser check was run).

## Remains
- Owner decision on the empty-candle message.
- b1 (dated close in the stock header) is still a gap on main; belongs to the StockDetail owner.
- Independent review of #520; not merged, #509 and #520 left open.
