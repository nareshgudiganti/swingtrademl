import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { BrainDecision } from '../api/types'
import { NOT_A_PROMISE, WhatWouldChange, changeLines } from './WhatWouldChange'

const base: BrainDecision = {
  id: 1,
  run_id: 'r1',
  symbol: 'HDFCBANK',
  kind: 'idea',
  word: 'WATCH',
  reasons: ['Good idea, but the risk check said no: Every free position slot went to a stronger idea in this run.'],
  entry_low: null,
  entry_high: null,
  target: null,
  stop: null,
  qty: 0,
  horizon_days: 15,
  confidence: 0.58,
  evidence_text: null,
  downgraded_from: 'TRADE',
  downgrade_reason: 'Good idea, but the risk check said no: Every free position slot went to a stronger idea in this run.',
  overruled_word: null,
  overrule_reason: null,
  overruled_by: null,
  overruled_at: null,
  what_would_change: [
    { key: 'slots_taken_by_stronger', text: 'A position slot would need to be free for it.' },
    { key: 'careful_market_falling', text: 'The stock would need to start rising, or the market mode return to NORMAL.' },
  ],
}

describe('changeLines', () => {
  it('shows lines for WATCH, WAIT and AVOID ideas', () => {
    for (const word of ['WATCH', 'WAIT', 'AVOID'] as const) {
      expect(changeLines({ ...base, word })).toHaveLength(2)
    }
  })

  it('shows nothing for a TRADE, a holding, or an older API without the field', () => {
    expect(changeLines({ ...base, word: 'TRADE' })).toEqual([])
    expect(changeLines({ ...base, kind: 'holding', word: 'MONITOR' })).toEqual([])
    const { what_would_change: _omit, ...older } = base
    expect(changeLines(older)).toEqual([])
  })

  it("follows the brain's own word, not an owner overrule", () => {
    expect(changeLines({ ...base, overruled_word: 'TRADE' })).toHaveLength(2)
  })
})

describe('WhatWouldChange', () => {
  it('lists every condition in order with the not-a-promise note', () => {
    const html = renderToString(<WhatWouldChange decision={base} />)
    expect(html).toContain('What would change this?')
    expect(html).toContain('most important first')
    const first = html.indexOf('A position slot would need to be free')
    const second = html.indexOf('The stock would need to start rising')
    expect(first).toBeGreaterThan(-1)
    expect(second).toBeGreaterThan(first)
    expect(html).toContain(NOT_A_PROMISE.slice(0, 40))
  })

  it('says "Not known" plainly when the API could not map the reason', () => {
    const html = renderToString(
      <WhatWouldChange
        decision={{ ...base, what_would_change: [{ key: 'unknown', text: 'Not known from the stored record.' }] }}
      />,
    )
    expect(html).toContain('Not known from the stored record.')
    expect(html).toContain('this would need to change')
  })

  it('renders nothing for a TRADE', () => {
    expect(renderToString(<WhatWouldChange decision={{ ...base, word: 'TRADE' }} />)).toBe('')
  })
})
