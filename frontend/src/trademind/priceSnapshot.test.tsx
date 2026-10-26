// The price on a stock page is labelled with what it is and as of when; a stale, delayed or mismatched
// price is never shown as a plain live number. The brain decision on the page is a separate, frozen thing.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, PriceSnapshot } from '../api/types'
import { StockHeader } from './stockParts'

const decision = { symbol: 'JAMNAAUTO', kind: 'idea', reasons: [] } as unknown as BrainDecision

const snap = (over: Partial<PriceSnapshot>): PriceSnapshot => ({
  symbol: 'JAMNAAUTO',
  state: 'live',
  price: 124.45,
  price_ts: '2026-10-26T08:33:00Z',
  price_date: null,
  prev_close: 123.57,
  prev_close_date: '2026-10-23',
  change_pct: 0.71,
  age_seconds: 60,
  prev_close_mismatch: false,
  note: 'Live price as of 26 Oct, 14:03 IST.',
  ...over,
})

function header(snapshot: PriceSnapshot | undefined, last: number, prev: number, change: number | null) {
  return renderToString(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <StockHeader decision={decision} last={last} prev={prev} change={change} snapshot={snapshot} withBuy={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the stock header price', () => {
  it('shows a live price with its timestamp and no "at last close"', () => {
    const html = header(snap({}), 124.45, 123.57, 0.88)
    expect(html).toContain('124.45')
    expect(html).toContain('Live price as of 26 Oct, 14:03 IST.')
    expect(html).toContain('data-state="live"')
    expect(html).not.toContain('at last close')
  })

  it('without a snapshot it falls back to the stored close and says so', () => {
    const html = header(undefined, 123.57, 128.15, -4.58)
    expect(html).toContain('at last close')
    expect(html).not.toContain('data-testid="price-note"')
  })

  it('a stale price carries its warning note', () => {
    const html = header(
      snap({ state: 'stale', change_pct: null, note: 'Price on file is old (23 Oct, 15:29 IST); not shown as live.' }),
      123.57,
      128.15,
      null,
    )
    expect(html).toContain('data-state="stale"')
    expect(html).toContain('not shown as live')
  })

  it('a delayed feed is flagged with its age', () => {
    const html = header(snap({ state: 'delayed', note: 'Delayed price from 26 Oct, 13:56 IST (8 min old).' }), 124, 123.57, 0.43)
    expect(html).toContain('data-state="delayed"')
    expect(html).toContain('8 min old')
  })

  it('a mismatched previous close hides the move instead of printing one', () => {
    const html = header(
      snap({ prev_close_mismatch: true, change_pct: null, note: 'Live price. The move is hidden because two sources disagree on yesterday’s close.' }),
      124.45,
      123.57,
      null,
    )
    expect(html).toContain('124.45')
    expect(html).not.toContain('▲')
    expect(html).not.toContain('▼')
    expect(html).toContain('two sources disagree')
  })

  it('a holiday shows the last session’s close with its date', () => {
    const html = header(
      snap({ state: 'holiday', price: 102, price_ts: null, price_date: '2026-10-19', note: 'Market holiday today; showing the close of 19 Oct.' }),
      102,
      100,
      2,
    )
    expect(html).toContain('data-state="holiday"')
    expect(html).toContain('showing the close of 19 Oct')
  })
})
