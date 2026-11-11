// Pure numbers behind the Portfolio charts and the closed-trades scoreboard. Display only: nothing here buys, sells
// or changes a stop, a size or a limit. Every input is a server row (open position or finished trade).

export const SLICE_COLORS = ['#3f55d6', '#1f9d6b', '#e0a72b', '#d9486a', '#7a4fd6', '#17a2b8', '#e8702a', '#5a6b8c']

export type Slice = { name: string; value: number; pct: number; color: string }

type Held = { symbol: string; sector?: string | null; current_value: number }

function slicesFrom(entries: [string, number][], maxSlices: number): Slice[] {
  const positive = entries.filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
  const total = positive.reduce((s, [, v]) => s + v, 0)
  if (total <= 0) return []
  // Keep the biggest ones; fold the long tail into "Others" so the ring stays readable.
  const keep = positive.length > maxSlices ? positive.slice(0, maxSlices - 1) : positive
  const rest = positive.length > maxSlices ? positive.slice(maxSlices - 1).reduce((s, [, v]) => s + v, 0) : 0
  const all: [string, number][] = rest > 0 ? [...keep, ['Others', rest]] : keep
  return all.map(([name, value], i) => ({
    name,
    value,
    pct: (value / total) * 100,
    color: SLICE_COLORS[i % SLICE_COLORS.length] ?? '#5a6b8c',
  }))
}

/** Share of the money held in each stock, biggest first. */
export function allocationByStock(rows: Held[], maxSlices = 8): Slice[] {
  const m = new Map<string, number>()
  for (const r of rows) m.set(r.symbol, (m.get(r.symbol) ?? 0) + r.current_value)
  return slicesFrom([...m.entries()], maxSlices)
}

/** Share of the money held in each sector; a stock with no sector counts as "Unclassified". */
export function allocationBySector(rows: Held[], maxSlices = 8): Slice[] {
  const m = new Map<string, number>()
  for (const r of rows) {
    const name = r.sector || 'Unclassified'
    m.set(name, (m.get(name) ?? 0) + r.current_value)
  }
  return slicesFrom([...m.entries()], maxSlices)
}

type Done = { symbol: string; net_pnl: number; is_win: boolean; quantity: number; entry_price: number }

export type ClosedSummary = {
  count: number
  wins: number
  losses: number
  /** 0–100, or null when nothing has closed yet (never show 0% for "no data"). */
  winRate: number | null
  net: number
  avgWin: number | null
  avgLoss: number | null
  best: { symbol: string; net: number } | null
  worst: { symbol: string; net: number } | null
}

/** The scoreboard for finished trades: how many, how many won, and what they made after charges. */
export function closedSummary(trades: Done[]): ClosedSummary {
  const wins = trades.filter((t) => t.is_win)
  const losses = trades.filter((t) => !t.is_win)
  const sum = (xs: Done[]) => xs.reduce((s, t) => s + t.net_pnl, 0)
  const byNet = [...trades].sort((a, b) => b.net_pnl - a.net_pnl)
  const pick = (t?: Done) => (t ? { symbol: t.symbol, net: t.net_pnl } : null)
  return {
    count: trades.length,
    wins: wins.length,
    losses: losses.length,
    winRate: trades.length ? (wins.length / trades.length) * 100 : null,
    net: sum(trades),
    avgWin: wins.length ? sum(wins) / wins.length : null,
    avgLoss: losses.length ? sum(losses) / losses.length : null,
    best: pick(byNet[0]),
    worst: pick(byNet.length > 1 ? byNet[byNet.length - 1] : undefined),
  }
}
