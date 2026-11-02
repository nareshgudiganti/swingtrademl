import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { LanePick } from '../api/types'
import pageSource from './HorizonPicks.tsx?raw'
import { PicksTable, pctText } from './HorizonPicks'

function pick(over: Partial<LanePick> = {}): LanePick {
  return {
    horizon_days: 5,
    lane: 'h05',
    run_no: 1,
    signal_day: '2026-11-03',
    symbol: 'AAA',
    cap: 'large',
    cap_label: 'Large cap',
    rank: 1,
    score: 0.7,
    model_id: 2,
    model_version: 'v2',
    status: 'open',
    entry_day: null,
    entry_price: null,
    exit_day: null,
    exit_price: null,
    exit_reason: null,
    net_return: null,
    ...over,
  }
}

const html = (rows: LanePick[]) => renderToString(<PicksTable rows={rows} />).replace(/<!-- -->/g, '')

describe('Horizon picks', () => {
  it('tags every row with its horizon and cap size', () => {
    const out = html([pick(), pick({ symbol: 'BBB', cap_label: 'Mid cap', horizon_days: 10 })])
    expect(out).toContain('5-day')
    expect(out).toContain('10-day')
    expect(out).toContain('Large cap')
    expect(out).toContain('Mid cap')
  })

  it('says "Not yet" and a dash for a pick with no entry or result, never zero', () => {
    const out = html([pick()])
    expect(out).toContain('Not yet')
    expect(out).toContain('—')
    expect(out).not.toContain('0.00%')
  })

  it('shows a finished result with its sign', () => {
    expect(pctText(0.0184)).toBe('+1.84%')
    expect(pctText(-0.041)).toBe('-4.10%')
    expect(pctText(null)).toBe('—')
  })

  it('says plainly when there are no picks', () => {
    expect(html([])).toContain('No picks recorded yet')
  })

  it('has no buy button and no write call', () => {
    expect(pageSource).not.toMatch(/\bBuy\b|\bBUY\b|useMutation|api\.(post|patch|put|del)/)
  })
})
