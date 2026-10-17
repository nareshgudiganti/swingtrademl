import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import StockBrief from './StockBrief'
import type { StockBriefData } from './types'
import UpcomingEvents from './UpcomingEvents'

const HEADINGS = [
  'What is this company?',
  'What does the brain say today, and why?',
  'What is the plan?',
  'How much money is at stake?',
  'Is anything coming up?',
  'Has this kind of idea worked before?',
]

const gap = (why: string) => ({ answer: 'Not available', available: false, why })

const empty: StockBriefData = {
  symbol: 'INFY',
  as_of: null,
  q1_company: gap('No company name is stored'),
  q2_brain: gap('The brain\'s last run was on 15 Oct 2026'),
  q3_plan: gap('plan why'),
  q4_money: { ...gap('money why') },
  q5_events: { answer: 'Nothing scheduled in the next 15 trading days', available: true, why: null, events: [] },
  q6_evidence: { answer: 'Not proven', available: true, why: null, claim: 'model_ranking_predictive' },
}

describe('StockBrief', () => {
  it('shows the six headed sections in order', () => {
    const out = renderToString(<StockBrief data={empty} />)
    const at = HEADINGS.map((h) => out.indexOf(h))
    expect(at.every((i) => i >= 0)).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
  })
  it('shows the why of every unavailable answer', () => {
    const out = renderToString(<StockBrief data={empty} />)
    for (const why of ['No company name is stored', '15 Oct 2026', 'plan why', 'money why'])
      expect(out).toContain(why.replace("'", '&#x27;'))
  })
  it('shows the evidence wording and the money block when available', () => {
    const data: StockBriefData = {
      ...empty,
      q4_money: {
        answer: 'x',
        available: true,
        why: null,
        invested: 1000,
        loss_if_stop: 40,
        gain_if_target: 80,
        gain_if_half_out: 60,
        charges_round_trip: 5,
      },
    }
    const out = renderToString(<StockBrief data={data} />)
    expect(out).toContain('Not proven')
    expect(out).toContain('₹ at stake')
  })
})

describe('UpcomingEvents', () => {
  it('has an exact empty state', () => {
    expect(renderToString(<UpcomingEvents events={[]} />)).toContain(
      'Nothing scheduled in the next 15 trading days',
    )
  })
  it('lists events in plain words', () => {
    const out = renderToString(
      <UpcomingEvents
        events={[
          {
            symbol: 'INFY',
            kind: 'results',
            date: '2026-10-19',
            trading_days_away: 1,
            detail: '',
            plain: 'Results tomorrow — prices can jump either way',
          },
        ]}
      />,
    )
    expect(out).toContain('INFY')
    expect(out).toContain('Results tomorrow')
  })
})
