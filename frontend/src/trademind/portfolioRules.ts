// The new look's Portfolio (pages/PortfolioNew.tsx): money summary, tonight's read on each held stock, room for new
// trades and the safety net. Pure functions, no hooks. Display only: nothing here buys, sells or changes a limit.
//
// Honesty rules:
//   * every number comes from the server (portfolio summary, positions, risk limits, safety state, status) or the
//     brain's stored run; when the server does not give it (or refuses it to this viewer), it is not shown;
//   * a rule's live state ("On", "Paused", "Off") is shown only when the server reports it; otherwise the rule is
//     shown as "Every trade" (it applies to every trade, but no switch is reported);
//   * the owner-only answers (risk limits, safety switch, the account's fall from its peak) are passed in only for
//     the owner, so a non-owner sees the rules without those numbers;
//   * "money room" is used ONLY for the at-most-N%-invested limit of a careful market (deployable_fraction).

import type {
  BrainDecision,
  BrainRun,
  CurrentLimits,
  DetailedPosition,
  PortfolioSummary,
  SectorExposure,
  SystemState,
  SystemStatus,
} from '../api/types'
import { scoreChange, scoreNow } from './HeldRead'
import { finalWord, holdingsFrom } from './live'
import { withoutScorePercent } from './scoreText'

// ------------------------------------------------------------- money --

export type MoneyFigures = { total: number; invested: number; cash: number; investedPct: number | null; held: number }

export function moneyFigures(s: PortfolioSummary): MoneyFigures {
  const investedPct = s.total_value > 0 ? Math.round((s.holdings_value / s.total_value) * 100) : null
  return { total: s.total_value, invested: s.holdings_value, cash: s.cash, investedPct, held: s.open_positions }
}

// ------------------------------------------------------ held stocks --

export type HeldRow = {
  symbol: string
  position: DetailedPosition | null
  decision: BrainDecision | null
  /** Tonight's word from the brain (HOLD / MONITOR / REDUCE / EXIT), or null when the run did not read it. */
  word: string | null
  why: string | null
  /** Today's model score out of 100 and the change since the previous daily reading, only when stored. */
  score: number | null
  change: number | null
}

/** The held stocks: the bot's positions when the server gives them, else the brain's holdings alone. */
export function heldRows(positions: DetailedPosition[] | undefined, run: BrainRun | undefined): HeldRow[] {
  const holdings = run ? holdingsFrom(run) : []
  const bySymbol = new Map(holdings.map((d) => [d.symbol.toUpperCase(), d] as const))
  const row = (symbol: string, p: DetailedPosition | null): HeldRow => {
    const d = bySymbol.get(symbol.toUpperCase()) ?? null
    const now = p ? scoreNow(p) : null
    return {
      symbol,
      position: p,
      decision: d,
      word: d ? finalWord(d) : null,
      why: d?.reasons[0] ? withoutScorePercent(d.reasons[0]) : null,
      score: now == null ? null : Math.round(now * 100),
      change: p ? scoreChange(p) : null,
    }
  }
  if (positions) return positions.map((p) => row(p.symbol, p))
  return holdings.map((d) => row(d.symbol, null))
}

/** "2 HOLD · 1 MONITOR · 1 EXIT" for the rows the brain read. */
export function wordSummary(rows: HeldRow[]): string {
  const order = ['HOLD', 'MONITOR', 'REDUCE', 'EXIT']
  const counts = new Map<string, number>()
  for (const r of rows) if (r.word) counts.set(r.word, (counts.get(r.word) ?? 0) + 1)
  return order.filter((w) => counts.get(w)).map((w) => `${counts.get(w)} ${w}`).join(' · ')
}

// ----------------------------------------------------------- room --

export type MoneyRoom = { limitPct: number; ceiling: number; invested: number; room: number; regime: string; limiting: boolean }

/** The careful-market money room: at most N% of the account invested. Null when the server gave no limits. */
export function moneyRoom(l: CurrentLimits | undefined): MoneyRoom | null {
  if (!l) return null
  return {
    limitPct: Math.round(l.deployable_fraction * 100),
    ceiling: l.deployable_ceiling_inr,
    invested: l.invested_inr,
    room: l.room_inr,
    regime: l.plain_regime,
    limiting: l.deployable_fraction < 1,
  }
}

// ------------------------------------------------------- safety net --

export type RuleState = 'on' | 'off' | 'paused' | 'every' | 'warn'
export type SafetyRule = { key: string; text: string; detail?: string; state: RuleState }

export const RULE_STATE_LABEL: Record<RuleState, string> = {
  on: 'On',
  off: 'Off',
  paused: 'Paused',
  every: 'Every trade',
  warn: 'Check',
}

const pct = (fraction: number) => `${Math.round(fraction * 1000) / 10}%`

/** Every rule of the safety net, with its live state where the server reports it. Owner-only inputs are undefined
 *  for everyone else. */
export function safetyRules(input: {
  limits?: CurrentLimits
  safety?: SystemState
  /** The account's fall from its peak now, in % (owner only). */
  ddPct?: number | null
  status?: SystemStatus
}): SafetyRule[] {
  const { limits, safety, status } = input
  const rules: SafetyRule[] = []

  rules.push({ key: 'stop', text: 'Sell if a stock falls 4% below its buy price', state: 'every' })
  if (limits && !limits.scale_out_enabled) {
    rules.push({
      key: 'half',
      text: 'Sell half at +5%, the rest at the +8% target',
      detail: 'Off at this account size: the whole position is sold at +8% or at the stop.',
      state: 'off',
    })
  } else {
    rules.push({ key: 'half', text: 'Sell half at +5%, the rest at the +8% target', state: limits ? 'on' : 'every' })
  }
  rules.push({ key: 'days', text: 'Sell within 15 trading days', state: 'every' })

  // The 15% halt. The current fall is an owner-only number.
  const haltPct = limits ? limits.max_drawdown_pct * 100 : 15
  const halt = `Stop all new buys if the account falls ${Math.round(haltPct)}% from its peak`
  if (limits && input.ddPct != null) {
    const dd = Math.max(0, input.ddPct)
    rules.push({
      key: 'drawdown',
      text: halt,
      detail: `Now ${dd.toFixed(1)}% below its peak.`,
      state: dd >= haltPct ? 'paused' : 'on',
    })
  } else {
    rules.push({ key: 'drawdown', text: halt, state: limits ? 'on' : 'every' })
  }

  if (limits?.sector_rule === 'one_per_sector') {
    rules.push({ key: 'sector', text: 'At most one stock in each sector', detail: 'The rule for the smallest account size.', state: 'on' })
  } else if (limits?.sector_cap_pct != null) {
    rules.push({ key: 'sector', text: `At most ${pct(limits.sector_cap_pct)} of the account in one sector`, state: 'on' })
  } else {
    rules.push({ key: 'sector', text: 'At most 25% of the account in one sector', state: limits ? 'warn' : 'every' })
  }

  const room = moneyRoom(limits)
  if (room) {
    rules.push({
      key: 'careful',
      text: room.limiting
        ? `${room.regime}: at most ${room.limitPct}% of the account invested`
        : 'In a careful market, less of the account is invested',
      detail: room.limiting ? undefined : `Not limiting now (${room.regime}).`,
      state: 'on',
    })
  } else {
    rules.push({ key: 'careful', text: 'In a careful market, less of the account is invested', state: 'every' })
  }

  if (safety) {
    rules.push({
      key: 'switch',
      text: 'Owner’s stop switch for new buys',
      detail: safety.new_entries_enabled ? 'New buys are allowed.' : `New buys are paused${safety.halt_reason ? `: ${safety.halt_reason}` : '.'}`,
      state: safety.new_entries_enabled ? 'on' : 'paused',
    })
  }

  rules.push({ key: 'data', text: 'Bad or old prices never make a decision bolder', state: 'every' })

  if (status) {
    const paper = status.trading_mode === 'paper' && !status.live_trading_enabled
    rules.push({
      key: 'paper',
      text: 'The bot uses paper money only; real orders are off',
      detail: paper ? undefined : 'The server is not in paper mode. Check before trusting any figure here.',
      state: paper ? 'on' : 'warn',
    })
  } else {
    rules.push({ key: 'paper', text: 'The bot uses paper money only; real money is the owner’s decision', state: 'every' })
  }
  return rules
}

// ------------------------------------------------------------ sectors --

export type SectorBar = { sector: string; pct: number; ofCap: number; over: boolean }

/** Sector bars against the cap (default 25%). From the risk limits (owner), else from the positions' own sector
 *  and value against the account total. [] when neither says. */
export function sectorBars(
  opts: { exposures?: SectorExposure[]; positions?: DetailedPosition[]; total?: number | null; capPct?: number | null },
): SectorBar[] {
  const cap = (opts.capPct ?? 0.25) * 100
  let list: { sector: string; pct: number }[] = []
  if (opts.exposures) list = opts.exposures.map((e) => ({ sector: e.sector, pct: e.pct_of_portfolio * 100 }))
  else if (opts.positions && opts.total && opts.total > 0) {
    const sums = new Map<string, number>()
    for (const p of opts.positions) if (p.sector) sums.set(p.sector, (sums.get(p.sector) ?? 0) + p.current_value)
    list = [...sums].map(([sector, v]) => ({ sector, pct: (v / opts.total!) * 100 }))
  }
  return list
    .sort((a, b) => b.pct - a.pct)
    .map((s) => ({ sector: s.sector, pct: s.pct, ofCap: Math.min(100, (s.pct / cap) * 100), over: s.pct > cap }))
}

// -------------------------------------------------------------- chart --

export type ChartRange = '1M' | '3M' | 'ALL'
export const RANGE_DAYS: Record<ChartRange, number | null> = { '1M': 31, '3M': 92, ALL: null }

/** The points inside a range, counted back from the newest point's date. */
export function pointsInRange<T extends { date: string }>(points: T[], range: ChartRange): T[] {
  const days = RANGE_DAYS[range]
  if (days == null || points.length === 0) return points
  const last = new Date(`${points[points.length - 1]!.date.slice(0, 10)}T00:00:00Z`).getTime()
  const from = last - days * 86_400_000
  return points.filter((p) => new Date(`${p.date.slice(0, 10)}T00:00:00Z`).getTime() >= from)
}
