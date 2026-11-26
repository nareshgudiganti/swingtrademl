// Plain words for two different things that sit side by side on a stock: the model's score and the Brain's plan.
// The score comes from the existing 5-day models; the plan (target, stop, window) is the Brain's own rule, read
// from the server (tradingRules.ts). They have not been tested together, and the score is a ranking, not a chance
// of profit.
import { horizonRule, planDays, stopText, targetText } from './tradingRules'

export const scoreVsPlan = (): string => {
  const five = horizonRule(5)
  return (
    `The score is the model’s ${five.horizon}-day reading: how strongly it ranks this stock for a +${five.targetPct}% rise within ${five.max_sessions} trading days. ` +
    `The trade plan (${targetText()} target, ${stopText()} stop, up to ${planDays()} trading days) is a separate rule. The score has not been tested ` +
    'against that plan yet, so the plan is not backed by the score’s record.'
  )
}

export const SCORE_VS_PLAN_SHORT = 'The plan is a separate rule from the model’s 5-day score and has not been tested with it yet.'

/**
 * Stock header "Horizon" lines (F3, label only): the forecast window (from the 5-day rule) and the longest hold
 * (from the decision's own horizon_days). A value that is missing gives no line (null): nothing is invented.
 */
export const forecastAndHold = (
  maxHoldDays: number | null | undefined,
): { forecast: string | null; hold: string | null } => {
  let sessions: number | null = null
  try {
    sessions = horizonRule(5).max_sessions
  } catch {
    sessions = null
  }
  return {
    forecast: sessions ? `Forecast: ${sessions} trading days (the window the score looks at)` : null,
    hold: maxHoldDays ? `Longest hold: up to ${maxHoldDays} trading days (when the plan sells)` : null,
  }
}
