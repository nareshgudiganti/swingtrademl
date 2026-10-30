// One vocabulary for every brain screen: one tone per decision word, one
// plain label and explanation per market mode, the step labels, the plain
// name of every brain part and the trace wording. The brain console
// (pages/Brain.tsx) imports its module names and trace wording from here too.
// It also holds the glossary (GLOSSARY, at the bottom) that <Term> shows on tap.

import type { BrainTraceEvent, HoldingWord, IdeaWord, MarketMode } from '../api/types'

export type Tone = 'pos' | 'warn' | 'neg' | 'neutral'
export type TagColor = 'green' | 'amber' | 'red' | 'blue' | 'violet'

// TRADE/HOLD are the brain's positive words. WATCH/WAIT/MONITOR ask for
// patience. AVOID/REDUCE/EXIT are its negative words. A word the brain
// hasn't told us about is neutral — never shown as green.
const WORD_TONE: Record<string, Tone> = {
  TRADE: 'pos',
  HOLD: 'pos',
  WATCH: 'warn',
  WAIT: 'warn',
  MONITOR: 'warn',
  AVOID: 'neg',
  REDUCE: 'neg',
  EXIT: 'neg',
}

/** What a screen prints for a brain word. The stored word stays TRADE; a customer reads BUY. */
export function wordLabel(word: string): string {
  return word === 'TRADE' ? 'BUY' : word
}

export function wordTone(word: string): Tone {
  return WORD_TONE[word] ?? 'neutral'
}

/** `tm-pos` / `tm-warn` / `tm-neg` / `tm-neutral` for colouring a word in
 * plain text (see trademind.css). */
export function wordClassName(word: string): string {
  return `tm-${wordTone(word)}`
}

const TONE_TAG_COLOR: Record<Tone, TagColor> = { pos: 'green', warn: 'amber', neg: 'red', neutral: 'blue' }

/** The colour for ui.tsx's <Tag>, derived from the same one tone per word. */
export function wordTagColor(word: string): TagColor {
  return TONE_TAG_COLOR[wordTone(word)]
}

export const MARKET_LABEL: Record<string, string> = {
  NORMAL: 'Normal',
  DEFENSIVE: 'Careful',
  NO_NEW_TRADES: 'No new trades',
}

export const MARKET_PLAIN: Record<string, string> = {
  NORMAL: 'New ideas are allowed at full size.',
  DEFENSIVE: 'Careful market: at most two new ideas, at half size.',
  NO_NEW_TRADES: 'No new buys today. Stocks you hold are still watched and sold as usual.',
}

export const MARKET_TONE: Record<string, 'green' | 'amber' | 'red'> = {
  NORMAL: 'green',
  DEFENSIVE: 'amber',
  NO_NEW_TRADES: 'red',
}

// Same step names as the brain console (Brain.tsx's own STEP_LABEL).
export const STEP_LABEL: Record<string, string> = {
  perceive: '1 · Look at the data',
  state: '2 · Read the market',
  recognise: '3 · Recognise the situation',
  remember: '4 · Remember similar times',
  reason: '5 · Form an opinion',
  risk: '6 · Safety check',
  decide: '7 · Decide',
  learn: '8 · Learn from results',
}

// Plain names for the brain's parts. The codes (M01…) are the build plan's
// labels — kept only as a hover tooltip, never as the visible name.
export const MODULE_PLAIN: Record<string, { name: string; does: string }> = {
  M00: { name: 'Brain core', does: 'Runs the steps in order and applies the safety rules.' },
  M01: { name: 'Data check', does: 'Checks the prices are fresh and believable before anything else uses them.' },
  M02: { name: 'Price reader', does: "Turns each stock's price history into simple facts: trend, momentum, swings and volume." },
  M03: { name: 'Market snapshot', does: 'Puts the market, the sectors, each stock and your account into one picture.' },
  M04: {
    name: 'Situation spotter',
    does: 'Names what is going on: a pullback, a breakout, a correction, a crash, or something never seen before.',
  },
  M05: { name: 'Memory of similar times', does: 'Looks up what happened after similar days in the past.' },
  M06: { name: 'Combined opinion', does: 'Blends all the signals into one score and checks it against past results.' },
  M07: { name: 'Safety check', does: 'Applies your money and risk limits. It can only say no or make a trade smaller.' },
  M08: {
    name: 'Decision maker',
    does: 'Turns everything into one word per stock: TRADE, WATCH, WAIT or AVOID (HOLD, MONITOR, REDUCE or EXIT for stocks you own).',
  },
  M09: { name: 'Learning from results', does: 'Scores finished ideas and suggests changes. Nothing changes until you accept.' },
  M10: { name: 'Market mood', does: 'Decides whether the market is normal, needs care, or is too risky for new trades.' },
  M11: { name: 'Sector strength', does: 'Ranks sectors against NIFTY, so stocks in stronger sectors get a small nudge.' },
  M12: { name: 'Chart patterns', does: 'Spots set-ups such as pullbacks and breakouts, and unusual buying.' },
  M13: { name: 'News and events', does: 'Watches for results dates, splits, bonuses and exchange warnings.' },
  M14: { name: 'Portfolio balance', does: 'Checks whether a new idea moves together with stocks you already hold.' },
  M15: { name: 'Trade tracker', does: 'Follows each stock you hold, day by day, against how similar trades went.' },
  M16: { name: 'Alerts', does: 'Sends one Telegram message a day with what needs your attention.' },
  M17: { name: 'Brain console', does: 'The screen that shows the brain at work.' },
  M18: { name: 'Go-live switch', does: 'Moves the brain from practice, to your approval, to automatic.' },
  fallback: { name: 'Simple built-in rule', does: 'Answers a step when no part of the brain is switched on for it.' },
}

export function moduleName(id: string): string {
  return MODULE_PLAIN[id]?.name ?? id
}

export function traceLine(e: BrainTraceEvent): string {
  if (e.module_id === 'fallback') return 'Answered by the simple built-in rule'
  const name = moduleName(e.module_id)
  switch (e.status) {
    case 'used':
      return `${name} answered`
    case 'shadow':
      return `${name} is on trial: its answer is recorded but not used yet`
    case 'skipped':
      return `${name} is switched off`
    case 'rejected':
      return `${name}'s answer was refused: ${e.reason}`
    default:
      return `${name} did not answer (${e.reason}); the simple built-in rule answered instead`
  }
}

// ---------------------------------------------------------------------------
// The glossary: one short, plain explanation per word the app shows. <Term>
// (term.tsx) opens these on tap, and the Learn page lists them all. Numbers
// come from the code, not from memory: +8% target / -4% stop / half at +5% /
// 15 trading days (brain/modules/m08_decide/policy.py), 15% drawdown pause
// (core/config.py MAX_PORTFOLIO_DRAWDOWN_PCT, services/risk.py), 25% per
// sector and one stock per sector on the smallest account
// (services/limits.py), careful market = at most 2 new ideas at half size
// (brain/modules/m07_risk/module.py).

export type DecisionWord = IdeaWord | HoldingWord
export type GlossaryKey =
  | DecisionWord
  | MarketMode
  | 'market_mode'
  | 'stop_loss'
  | 'target'
  | 'half_out'
  | 'horizon'
  | 'buy_zone'
  | 'drawdown'
  | 'sector'
  | 'model_score'
  | 'est_chance'
  | 'paper'
  | 'real'
  | 'unrealised'
  | 'quiet_hours'
  | 'digest'

export type GlossaryGroup = 'idea' | 'holding' | 'market' | 'plan' | 'money' | 'alerts'
export type GlossaryEntry = { label: string; text: string; group: GlossaryGroup }

export const IDEA_WORDS: IdeaWord[] = ['TRADE', 'WATCH', 'WAIT', 'AVOID']
export const HOLDING_WORDS: HoldingWord[] = ['HOLD', 'MONITOR', 'REDUCE', 'EXIT']
export const MARKET_MODES: MarketMode[] = ['NORMAL', 'DEFENSIVE', 'NO_NEW_TRADES']

export const GLOSSARY: Record<GlossaryKey, GlossaryEntry> = {
  TRADE: {
    label: 'TRADE',
    group: 'idea',
    text: 'Worth buying now, at the suggested size. It is only shown after the safety check has approved it, and it comes with a target and a stop-loss.',
  },
  WATCH: {
    label: 'WATCH',
    group: 'idea',
    text: 'Looks interesting, but not a buy today — for example the safety check said no, or the market needs care. Keep an eye on it.',
  },
  WAIT: {
    label: 'WAIT',
    group: 'idea',
    text: 'Nothing to do yet. The signals are weak, its sector is not among the strongest, or there is no clear set-up.',
  },
  AVOID: {
    label: 'AVOID',
    group: 'idea',
    text: "Stay away for now — for example the company's results are due soon, or the exchange has put the stock on its watch list.",
  },
  HOLD: {
    label: 'HOLD',
    group: 'holding',
    text: 'Keep the stock. Nothing worrying has shown up, and its target and stop-loss still apply.',
  },
  MONITOR: {
    label: 'MONITOR',
    group: 'holding',
    text: 'Keep it, but watch closely: it is not moving the way similar trades did, it is falling in a careful market, or it is doing worse than the market as a whole.',
  },
  REDUCE: {
    label: 'REDUCE',
    group: 'holding',
    text: 'Sell half. The stock is up 5% from the buy price, so half is sold to lock in that gain and the rest stays in for the +8% target.',
  },
  EXIT: {
    label: 'EXIT',
    group: 'holding',
    text: 'Sell all of it — usually because the price has fallen to the stop-loss.',
  },
  market_mode: {
    label: 'Market mode',
    group: 'market',
    text: "The brain's daily read of the whole market: Normal, Careful or No new trades. It decides how many new buys are allowed that day.",
  },
  NORMAL: {
    label: 'Normal',
    group: 'market',
    text: 'The market looks healthy. New ideas are allowed at full size.',
  },
  DEFENSIVE: {
    label: 'Careful',
    group: 'market',
    text: 'The market looks shaky. At most two new ideas, each at half the usual size.',
  },
  NO_NEW_TRADES: {
    label: 'No new trades',
    group: 'market',
    text: 'No new buys today — for example the market is too risky, the data is not reliable, or buying was paused. Stocks you hold are still watched and sold as usual.',
  },
  stop_loss: {
    label: 'Stop-loss',
    group: 'plan',
    text: 'The price at which the stock is sold to stop the loss growing: 4% below the buy price. It keeps one bad trade small.',
  },
  target: {
    label: 'Target',
    group: 'plan',
    text: 'The price at which the plan takes its profit: 8% above the buy price.',
  },
  half_out: {
    label: 'Sell half (first target)',
    group: 'plan',
    text: 'When a stock is up 5%, half of it is sold to lock in some profit. The rest stays in for the +8% target. (The smallest accounts do not split a holding in half.)',
  },
  horizon: {
    label: 'Horizon',
    group: 'plan',
    text: 'How long a trade is planned to last: at most 15 trading days, about three weeks. As a safety net, the bot sells anything still held 30 calendar days after buying it.',
  },
  buy_zone: {
    label: 'Buy around',
    group: 'plan',
    text: 'The price range where buying makes sense today. Well above it, the stock has already moved and the plan no longer fits.',
  },
  drawdown: {
    label: 'Drawdown',
    group: 'money',
    text: 'How far the account has fallen from its highest value so far. If it falls 15% below that high point, new buys are paused until it recovers.',
  },
  sector: {
    label: 'Sector',
    group: 'money',
    text: 'A group of companies in the same line of business, such as banks or IT. At most 25% of the account goes into one sector; the smallest accounts hold at most one stock per sector.',
  },
  model_score: {
    label: 'Model score',
    group: 'money',
    text: 'A number from 0 to 100 that the model uses to rank stocks against each other — higher means it likes the stock more. It is a ranking, not a chance of winning.',
  },
  est_chance: {
    label: 'Estimated chance',
    group: 'money',
    text: 'How often stocks with a similar score really went up 8% before falling 4%, within 15 trading days, on days the model had not seen. A guide, not a promise.',
  },
  paper: {
    label: 'Paper',
    group: 'money',
    text: 'Practice trading with pretend money. Nothing is really bought or sold, so no real money is at risk.',
  },
  real: {
    label: 'Real',
    group: 'money',
    text: 'Your actual Zerodha account: real money and real shares.',
  },
  unrealised: {
    label: 'Profit / loss so far',
    group: 'money',
    text: "What you would gain or lose on stocks you still hold if you sold them at today's price. It only becomes real when you sell.",
  },
  quiet_hours: {
    label: 'Quiet hours',
    group: 'alerts',
    text: 'A time window (India time) when everyday messages wait instead of buzzing your phone. They are sent together when the window ends. Sell and safety messages still come straight away.',
  },
  digest: {
    label: 'Daily digest',
    group: 'alerts',
    text: 'One message a day, at the time you choose, that collects the everyday messages instead of sending each one. Sell and safety messages still come straight away.',
  },
}

export function isGlossaryKey(k: string): k is GlossaryKey {
  return Object.prototype.hasOwnProperty.call(GLOSSARY, k)
}

export const GLOSSARY_GROUPS: { id: GlossaryGroup; title: string }[] = [
  { id: 'idea', title: 'Words for new ideas' },
  { id: 'holding', title: 'Words for stocks you hold' },
  { id: 'market', title: 'The market today' },
  { id: 'plan', title: 'The plan for each trade' },
  { id: 'money', title: 'Money, scores and accounts' },
  { id: 'alerts', title: 'Alerts on your phone' },
]
