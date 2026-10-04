// One vocabulary for every brain screen: one tone per decision word, one
// plain label and explanation per market mode, the step labels, the plain
// name of every brain part and the trace wording. The brain console
// (pages/Brain.tsx) imports its module names and trace wording from here too.

import type { BrainTraceEvent } from '../api/types'

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
