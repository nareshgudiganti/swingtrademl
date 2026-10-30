import type { ReactElement } from 'react'
import { renderToString as rawRender } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision } from '../api/types'
import type { BrainChanges, BrainChangeSide } from './changes'
import { ChangesSummaryView, IdeaChangeView, WhyNotTradeView } from './IdeaExplain'

// React marks text joins with <!-- -->; drop them so sentences can be checked whole.
const renderToString = (el: ReactElement) => rawRender(el).replace(/<!-- -->/g, '')

const decision = (over: Partial<BrainDecision>): BrainDecision => ({
  id: 1,
  run_id: 'r1',
  symbol: 'HDFCBANK',
  kind: 'idea',
  word: 'WATCH',
  reasons: [],
  entry_low: null,
  entry_high: null,
  target: null,
  stop: null,
  qty: 0,
  horizon_days: 15,
  confidence: 0.58,
  evidence_text: null,
  downgraded_from: null,
  downgrade_reason: null,
  overruled_word: null,
  overrule_reason: null,
  overruled_by: null,
  overruled_at: null,
  ...over,
})

const side = (over: Partial<BrainChangeSide> = {}): BrainChangeSide => ({
  word: 'WAIT',
  brain_word: 'WAIT',
  overruled_word: null,
  overrule_reason: null,
  reasons: ['Model score 52% is below the buy level 55%.'],
  downgraded_from: null,
  downgrade_reason: null,
  rank: 5,
  rank_of: 40,
  score_kind: 'model',
  ...over,
})

const changes = (ideas: BrainChanges['ideas']): BrainChanges => ({
  comparable: true,
  note: null,
  current: { run_id: 'r2', as_of: '2026-10-16T10:20:00Z', day: '2026-10-16', banner_mode: 'NORMAL' },
  previous: { run_id: 'r1', as_of: '2026-10-15T10:20:00Z', day: '2026-10-15', banner_mode: 'NORMAL' },
  ideas,
})

describe('WhyNotTradeView', () => {
  it('shows the stored reasons in plain words, without the account detail', () => {
    const risk = 'Good idea, but the risk check said no: Bank sector is already near its limit.'
    const html = renderToString(
      <WhyNotTradeView decision={decision({ reasons: [risk], downgraded_from: 'TRADE', downgrade_reason: risk })} />,
    )
    expect(html).toContain('Why not a BUY?')
    expect(html).toContain('holding back on a new buy today')
    expect(html).not.toContain('Bank sector is already near its limit.')
  })

  it('says so when nothing is stored', () => {
    const html = renderToString(<WhyNotTradeView decision={decision({ word: 'WAIT', reasons: [] })} />)
    expect(html).toContain('did not store a reason')
  })

  it('shows nothing for a TRADE or a holding', () => {
    expect(renderToString(<WhyNotTradeView decision={decision({ word: 'TRADE' })} />)).toBe('')
    expect(renderToString(<WhyNotTradeView decision={decision({ kind: 'holding', word: 'MONITOR' })} />)).toBe('')
  })

  it('never shows the raw score of a "below the buy level" reason', () => {
    const html = renderToString(
      <WhyNotTradeView decision={decision({ word: 'WAIT', reasons: ['Model score 52% is below the buy level 55%.'] })} />,
    )
    expect(html).toContain('not high enough')
    expect(html).not.toContain('52%')
    expect(html).not.toContain('55%')
  })
})

describe('IdeaChangeView', () => {
  it('shows a word change and the move in the ranking, never a percentage', () => {
    const html = renderToString(
      <IdeaChangeView
        data={changes([{ symbol: 'INFY', held_now: false, before: side({ rank: 12 }), now: side({ word: 'TRADE', reasons: ['Strong.'], rank: 2 }) }])}
        symbol="INFY"
      />,
    )
    expect(html).toContain('data-change="word"')
    expect(html).toContain('Changed from WAIT yesterday to TRADE today.')
    expect(html).toContain('Moved up 10 places in the ranking')
    expect(html).toContain('Why it was WAIT yesterday')
    expect(html).not.toContain('%')
  })

  it('shows the note when there is nothing to compare with', () => {
    const html = renderToString(
      <IdeaChangeView data={{ ...changes([]), comparable: false, previous: null, note: 'There is no earlier nightly run to compare with yet.' }} symbol="INFY" />,
    )
    expect(html).toContain('no earlier nightly run')
  })

  it('says when the stock was not an idea on either day', () => {
    expect(renderToString(<IdeaChangeView data={changes([])} symbol="XYZ" />)).toContain('did not list XYZ')
  })
})

describe('ChangesSummaryView', () => {
  const wrap = (data: BrainChanges) =>
    renderToString(
      <MemoryRouter>
        <ChangesSummaryView data={data} />
      </MemoryRouter>,
    )

  it('counts what changed and links each stock', () => {
    const html = wrap(
      changes([
        { symbol: 'INFY', held_now: false, before: side(), now: side({ word: 'TRADE', reasons: ['Strong.'] }) },
        { symbol: 'ITC', held_now: false, before: null, now: side() },
        { symbol: 'TCS', held_now: true, before: side(), now: null },
      ]),
    )
    expect(html).toContain('1 decision changed')
    expect(html).toContain('WAIT → TRADE')
    expect(html).toContain('1 new on the list today')
    expect(html).toContain('1 now held')
    expect(html).toContain('href="/trademind/stock/INFY"')
  })

  it('says when nothing changed', () => {
    expect(wrap(changes([{ symbol: 'ITC', held_now: false, before: side(), now: side() }]))).toContain('No decision changed')
  })
})
