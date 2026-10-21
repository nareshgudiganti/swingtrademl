import type { BrainDecision } from '../api/types'
import { CheckItem } from './ui'

/** The brain's own words this panel explains. TRADE has nothing to change; holdings use a
 *  different vocabulary. Uses the brain's word, not an owner overrule. */
const EXPLAINED = new Set(['WATCH', 'WAIT', 'AVOID'])

/** The lines to show, or [] when the panel should not appear. Display-only: the lines come
 *  from the API (`what_would_change`), which reads them from the stored reasons. */
export function changeLines(d: BrainDecision): { key: string; text: string }[] {
  if (d.kind !== 'idea' || !EXPLAINED.has(d.word)) return []
  return (d.what_would_change ?? []).filter((i) => i.text.trim() !== '')
}

export const NOT_A_PROMISE =
  'Read from the reasons stored with this decision. Other checks still run, so meeting these does not ' +
  'guarantee a TRADE — and a TRADE is never a promise that the trade will work.'

/** "What would change this?" for a WATCH / WAIT / AVOID idea. Shows nothing otherwise. */
export function WhatWouldChange({ decision }: { decision: BrainDecision }) {
  const lines = changeLines(decision)
  if (lines.length === 0) return null
  return (
    <section className="tm-card" style={{ marginTop: '1rem' }} aria-label="What would change this?">
      <div className="tm-card-head">
        <h4 className="tm-card-title">What would change this?</h4>
      </div>
      <p className="tm-dim" style={{ marginTop: 0 }}>
        For TradeMind to say TRADE, {lines.length === 1 ? 'this would need to change' : 'these would need to change'}
        {lines.length > 1 ? ' (most important first)' : ''}:
      </p>
      {lines.map((l) => (
        <CheckItem key={`${l.key}:${l.text}`} tone="neutral">
          {l.text}
        </CheckItem>
      ))}
      <p className="tm-note" style={{ marginTop: '0.6rem' }}>
        {NOT_A_PROMISE}
      </p>
    </section>
  )
}
