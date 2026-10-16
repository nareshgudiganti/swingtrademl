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
