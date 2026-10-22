import type { BrainDecision } from '../../api/types'

/** The beginner card reads the existing brain decision as-is (no new shape). */
export type BeginnerDecision = BrainDecision

/** Backend `money_at_stake` (numbers in rupees, already after charges). */
export interface MoneyAtStakeData {
  available: boolean
  why: string | null
  invested?: number | null
  loss_if_stop?: number | null
  gain_if_target?: number | null
  gain_if_half_out?: number | null
  charges_round_trip?: number | null
}

/** Backend events item (results / corporate action), counted in trading days. */
export interface EventItem {
  symbol: string
  kind: 'results' | 'corporate_action'
  date: string
  trading_days_away: number
  detail: string
  plain: string
}

/** One answer in the stock brief. Unavailable answers always carry a `why`. */
export interface BriefAnswer {
  answer: string
  available: boolean
  why: string | null
}

export interface StockBriefData {
  symbol: string
  as_of: string | null
  q1_company: BriefAnswer & { name?: string; sector?: string | null; size?: string | null }
  q2_brain: BriefAnswer & { word?: string; decision?: BeginnerDecision }
  q3_plan: BriefAnswer & {
    buy_zone?: [number, number]
    sell_half_price?: number
    sell_half_pct?: number
    target?: number
    stop?: number
    last_exit_day?: string
  }
  q4_money: BriefAnswer & MoneyAtStakeData
  q5_events: BriefAnswer & { events?: EventItem[] }
  q6_evidence: BriefAnswer & { claim?: string; claim_label?: string }
}

export interface EvidenceSummary {
  paper_label: string
  bot: {
    since: string | null
    profit_booked: number
    profit_open: number
    costs_paid: number
    worst_fall_from_peak_pct: number | null
    finished_trades: number
    win_rate_pct: number | null
    nifty_same_period_pct: number | null
    every_stock_same_period_pct: number | null
    enough_trades: boolean
    note: string
  }
  brain_trial: { since: string; finished: number; needed: number; sealed: boolean; sealed_note: string }
}

// oa11: GET /beginner/insights. Practice and real are separate objects; there is never a total.
export type InsightsPeriod = 'day' | 'week' | 'month'
export interface InsightsBook {
  finished: number
  wins: number
  net_pnl: number
  charges: number
  money_used: number
  return_pct: number | null
}
export interface InsightsBenchmark {
  pct: number | null
  why: string | null
  stocks?: number
}
export interface InsightsRow {
  key: string
  label: string
  from: string
  to: string
  paper: InsightsBook
  real: InsightsBook | null
  nifty_50: InsightsBenchmark
  every_stock: InsightsBenchmark
}
export interface InsightsData {
  period: InsightsPeriod
  today: string
  since: string | null
  paper_label: string
  real_label: string | null
  real_shown: boolean
  defs: string
  definitions: { paper: string; real?: string; nifty_50: string; every_stock: string }
  note: string
  rows: InsightsRow[]
}
