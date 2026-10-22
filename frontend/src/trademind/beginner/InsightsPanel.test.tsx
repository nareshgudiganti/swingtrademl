import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { BrainProgress, InsightsTable } from './InsightsPanel'
import type { InsightsData } from './types'

const book = (net: number) => ({ finished: 1, wins: net > 0 ? 1 : 0, net_pnl: net, charges: 5, money_used: 10000, return_pct: net / 100 })
const data = (realShown: boolean): InsightsData => ({
  period: 'week',
  today: '2026-10-22',
  since: '2026-09-28',
  paper_label: 'Practice money (paper)',
  real_label: realShown ? 'Real money (your Zerodha account)' : null,
  real_shown: realShown,
  defs: 'evidence-defs-v1',
  definitions: {
    paper: 'PAPER DEF',
    ...(realShown ? { real: 'REAL DEF' } : {}),
    nifty_50: 'NIFTY DEF',
    every_stock: 'EVERY DEF',
  },
  note: 'Practice money and real money are shown side by side and never added together.',
  rows: [
    {
      key: '2026-10-19',
      label: 'Week of 19 Oct',
      from: '2026-10-19',
      to: '2026-10-22',
      paper: book(111),
      real: realShown ? book(222) : null,
      nifty_50: { pct: 0.5, why: null },
      every_stock: { pct: null, why: 'The brain made no live practice run in these days.', stocks: 0 },
    },
  ],
})

describe('InsightsTable', () => {
  it('names every benchmark definition', () => {
    const html = renderToString(<InsightsTable data={data(true)} />)
    for (const d of ['PAPER DEF', 'REAL DEF', 'NIFTY DEF', 'EVERY DEF', 'evidence-defs-v1']) expect(html).toContain(d)
  })
  it('shows practice and real side by side and never a total', () => {
    const html = renderToString(<InsightsTable data={data(true)} />)
    expect(html).toContain('+₹111')
    expect(html).toContain('+₹222')
    expect(html).not.toContain('333')
    expect(html.toLowerCase()).not.toContain('total')
  })
  it('has no real column when the server did not send real figures', () => {
    const html = renderToString(<InsightsTable data={data(false)} />)
    expect(html).not.toContain('insights-real-head')
    expect(html).not.toContain('REAL DEF')
  })
  it('a missing benchmark says why', () => {
    expect(renderToString(<InsightsTable data={data(true)} />)).toContain('The brain made no live practice run')
  })
})

describe('BrainProgress', () => {
  const props = {
    trial: { since: '2026-10-14', finished: 4, needed: 30, sealed: true, sealed_note: 'Sealed until the review.' },
    gate: { word: 'Insufficient evidence', why: '4 of 30 finished.', cohort_from: '2026-10-14', cohort_to: '2026-10-22', cohort: 'c' },
    claims: [
      { claim: 'learning_changes', label: 'Changes proposed by learning (M09)', word: 'No frozen protocol yet', numeric: null, independence: null, independence_note: '', protocol_id: null, tested_subject: null, numbers: null, problems: [] },
    ],
    learning: { results_collected: 7, results_collected_label: 'graded ideas', changes_proposed: { open: 1, accepted: 2 }, learning_checks: 3, proven_improvement: null as never, note: '', redacted_fields: [] },
  }
  it('says Not proven, shows counts only', () => {
    const html = renderToString(<BrainProgress {...props} />)
    expect(html).toContain('Not proven')
    expect(html).toContain('4 of 30 finished')
    expect(html).toContain('Insufficient evidence')
    expect(html).toContain('No frozen protocol yet')
    expect(html).toContain('Changes proposed: 3')
  })
  it('says Not available, never a guess, when a part could not load', () => {
    const html = renderToString(<BrainProgress trial={null} gate={null} claims={null} learning={null} />)
    expect(html).toContain('Not proven')
    expect(html.match(/Not available/g)?.length).toBe(4)
  })
})
