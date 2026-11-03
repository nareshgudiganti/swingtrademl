// Plain words for two different things that sit side by side on a stock: the model's score and the Brain's plan.
// The score comes from the existing 5-day models; the plan (+8% target, -4% stop, up to 15 trading days) is the
// Brain's own rule. They have not been tested together, and the score is a ranking, not a chance of profit.

export const SCORE_VS_PLAN =
  'The score is the model’s 5-day reading: how strongly it ranks this stock for a +2% rise within 5 trading days. ' +
  'The trade plan (+8% target, −4% stop, up to 15 trading days) is a separate rule. The score has not been tested ' +
  'against that plan yet, so the plan is not backed by the score’s record.'

export const SCORE_VS_PLAN_SHORT = 'The plan is a separate rule from the model’s 5-day score and has not been tested with it yet.'
