// Pure mappers for the Risk, Learn and System screens — turning API shapes
// into what those screens draw. No hooks here, same spirit as live.ts's own
// mappers: easy to call from render, easy to test later.

import type { BrainDecision, BrainRun, EquityPoint, SectorExposure } from '../api/types'
import type { Point } from './data'

/** Ideas and holdings the brain actually turned down this run — a TRADE (or
 * a less careful holding word) brought down a notch, with the reason it
 * gave. Covers every downgrade, not only the risk gate's own: the gate is
 * mandatory and cannot be switched off, but a downgrade can also come from
 * stale data or a defensive market. */
export function refusedDecisions(run: BrainRun): BrainDecision[] {
  return run.decisions.filter((d) => d.downgraded_from != null)
}

/** The sector carrying the most of the portfolio right now, or null when
 * nothing is held in any sector. */
export function biggestSector(sectors: SectorExposure[]): SectorExposure | null {
  if (sectors.length === 0) return null
  return sectors.reduce((a, b) => (b.pct_of_portfolio > a.pct_of_portfolio ? b : a))
}

/** How far below its peak the portfolio sits right now (0..100), from the
 * most recent equity-curve point. Null when there is no history yet. */
export function currentDrawdownPct(points: EquityPoint[]): number | null {
  if (points.length === 0) return null
  return points[points.length - 1]!.drawdown_pct * 100
}

/** The drawdown chart's series: each day's fall from its peak-to-date, as a
 * negative percentage so it plots the same way the sample chart did. */
export function drawdownChartSeries(points: EquityPoint[]): Point[] {
  return points.map((p) => ({ t: p.date.slice(5), v: -Math.round(p.drawdown_pct * 1000) / 10 }))
}
