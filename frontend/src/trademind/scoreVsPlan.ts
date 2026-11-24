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
