// A stock's name everywhere it appears in a list: it opens that stock's page, and it carries the model's
// latest score beside it so a stock never shows without it. The score is the brain's latest run (cached,
// shared with every other component that reads it); where the run does not list the stock, no score is shown.

import { useMemo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { useLatestRun } from './live'
import { scorePoints } from './scoreText'

/** Today's model score (0-100) by symbol, from the brain's latest run. An idea's score wins over a holding's. */
export function useScoreBySymbol(): Map<string, number> {
  const run = useLatestRun().data
  return useMemo(() => {
    const out = new Map<string, number>()
    for (const d of run?.decisions ?? []) {
      const pts = scorePoints(d.confidence)
      if (pts == null) continue
      const key = d.symbol.toUpperCase()
      if (d.kind === 'idea' || !out.has(key)) out.set(key, pts)
    }
    return out
  }, [run])
}

export const stockPath = (symbol: string) => `/trademind/stock/${encodeURIComponent(symbol)}`

export default function StockLink({
  symbol,
  withScore = true,
  children,
}: {
  symbol: string
  /** False where the row already has its own score column. */
  withScore?: boolean
  /** Replaces the plain symbol text (a logo and name, say). */
  children?: ReactNode
}) {
  const scores = useScoreBySymbol()
  const score = withScore ? scores.get(symbol.toUpperCase()) : undefined
  return (
    <>
      <Link
        to={stockPath(symbol)}
        className="tm-strong tm-stocklink"
        onClick={(e) => e.stopPropagation()} // a row that opens a panel must not also toggle it
        title={`Open ${symbol}`}
      >
        {children ?? symbol}
      </Link>
      {score != null && (
        <span className="tm-scorechip" title="The model's score today, out of 100">
          {score}
        </span>
      )}
    </>
  )
}
