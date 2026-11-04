import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { DetailedPosition, Trade } from '../api/types'
import { filterSells, SellList, SellStatusTag, sellFilterOptions } from './HeldRead'
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

describe('the sell filter in the title', () => {
  const mk = (id: number, reason: string, label: string, day: string) =>
    trade({ id, exit_reason: reason, exit_reason_label: { TARGET_HIT: 'Target reached', STOP_LOSS_HIT: 'Stop-loss hit', SCALE_OUT: 'Sold part at first target' }[reason] ?? null, sell_label: label, book_label: 'Testing', exit_at: `2026-11-0${day}T05:00:00Z` })
  const all = [
    mk(1, 'SCALE_OUT', 'Partial SELL completed', '3'),
    mk(2, 'SCALE_OUT', 'Partial SELL completed', '3'),
    mk(3, 'STOP_LOSS_HIT', 'PAPER SELL executed', '2'),
    mk(4, 'TARGET_HIT', 'PAPER SELL executed', '2'),
  ]

  it('counts each choice and only offers choices that match something', () => {
    const o = sellFilterOptions(all)
    expect(o.total).toBe(4)
    expect(o.types).toEqual([['PAPER SELL executed', 2], ['Partial SELL completed', 2]])
    expect(o.reasons.map(([n]) => n).sort()).toEqual(['Sold part at first target', 'Stop-loss hit', 'Target reached'])
  })

  it('filters by type and by reason, and "all" keeps everything', () => {
    expect(filterSells(all, 'all')).toHaveLength(4)
    expect(filterSells(all, 'type:Partial SELL completed').map((t) => t.id)).toEqual([1, 2])
    expect(filterSells(all, 'type:PAPER SELL executed').map((t) => t.id)).toEqual([3, 4])
    expect(filterSells(all, 'reason:Stop-loss hit').map((t) => t.id)).toEqual([3])
    expect(filterSells(all, 'reason:Nothing like this')).toEqual([])
  })

  it('the title is a dropdown, not a fixed label', () => {
    const html = renderToString(<SellList trades={all} book="Testing" />)
    expect(html).toContain('data-testid="sell-filter"')
    expect(html).toContain('Sells: all (4)')
    expect(html).toContain('Partial SELL completed (2)')
    expect(html).not.toContain('Latest sells')
  })
})
