/** The risk layer records a rejection under a machine name. These are the
 * same limits in the words the rest of the app uses for them. Shared by the
 * classic Safety page and TradeMind's Admin > Risk event log, so both say the
 * same thing about the same event. */
export const RULE_LABEL: Record<string, string> = {
  SECTOR_CAP: 'Too much in one sector',
  POSITION_LIMIT: 'Already holding the maximum number of stocks',
  CAP_TIER: 'Small-company budget full',
  LIQUIDITY: 'Stock trades too little to buy this size',
  DEPLOYABLE: 'Market conditions cap how much goes out today',
  CASH_FLOOR: 'Would eat into the cash reserve',
  CASH: 'Not enough cash',
  DRAWDOWN: 'Account down too far — new buying halted',
  ENTRIES_HALTED: 'You halted new buying',
  COOLDOWN: 'Stopped out of this stock recently',
  DUPLICATE: 'Already holding this stock',
}

/** How many of the latest events both pages ask for (newest first). */
export const RISK_EVENT_LIMIT = 100

export const ruleLabel = (rule: string): string => RULE_LABEL[rule] ?? rule
