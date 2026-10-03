// One vocabulary for every TradeMind screen: one tone per decision word, one
// plain label and explanation per market mode, and the brain console's step
// labels and trace wording (kept byte-for-byte in sync with Brain.tsx's own
// copy by hand — neither file imports from the other).

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

export function traceLine(e: BrainTraceEvent): string {
  if (e.module_id === 'fallback') return 'Simple built-in answer (no module installed for this step)'
  switch (e.status) {
    case 'used':
      return `${e.module_id} answered`
    case 'shadow':
      return `${e.module_id} ran on trial — recorded, not used`
    case 'skipped':
      return `${e.module_id} is switched off`
    case 'rejected':
      return `${e.module_id}'s answer was refused: ${e.reason}`
    default:
      return `${e.module_id} did not answer (${e.reason}); the simple built-in answer was used`
  }
}
