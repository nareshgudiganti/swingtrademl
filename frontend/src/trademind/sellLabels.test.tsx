import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { DetailedPosition, Trade } from '../api/types'
import { SellStatusTag } from './HeldRead'
import { tradeRow } from './wave3Rules'

const trade = (over: Partial<Trade>): Trade =>
  ({
    id: 1, symbol: 'ABC', mode: 'paper', quantity: 10, entry_price: 100, exit_price: 105,
    entry_at: '2026-10-28T05:00:00Z', exit_at: '2026-11-02T05:00:00Z', holding_days: 5, gross_pnl: 50, charges: 5,
    net_pnl: 45, return_pct: 0.05, exit_reason: 'TARGET_HIT', exit_reason_label: 'Target reached', is_win: true,
    strategy_name: 'ml_swing_main',
    ...over,
  }) as Trade

describe('SELL labels', () => {
  it('a finished sale says what happened and which book it came from', () => {
    const row = tradeRow(trade({ sell_label: 'PAPER SELL executed', book_label: 'Bot' }), false)
    expect(row.ended).toContain('PAPER SELL executed (Bot)')
    expect(row.ended).toContain('Target hit')
  })

  it('a part-sale is labelled as partial', () => {
    const row = tradeRow(trade({ exit_reason: 'SCALE_OUT', sell_label: 'Partial SELL completed', book_label: 'Testing' }), false)
    expect(row.ended).toContain('Partial SELL completed (Testing)')
  })

  it('an older response without the label reads exactly as before', () => {
    expect(tradeRow(trade({}), false).ended).toMatch(/^Target hit/)
  })

  it('shows the open-position states and nothing when there is nothing to say', () => {
    const html = (status: string | null) => renderToString(<SellStatusTag p={{ sell_status: status } as DetailedPosition} />)
    expect(html('SELL review required')).toContain('SELL review required')
    expect(html('Exit check unavailable')).toContain('Exit check unavailable')
    expect(html(null)).toBe('')
  })
})
