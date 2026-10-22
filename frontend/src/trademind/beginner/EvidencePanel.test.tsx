import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import EvidencePanel from './EvidencePanel'
import type { EvidenceSummary } from './types'

const base: EvidenceSummary = {
  paper_label: 'Practice money (paper)',
  bot: {
    since: '2026-10-14',
    profit_booked: 1200,
    profit_open: -300,
    costs_paid: 45,
    worst_fall_from_peak_pct: 2.5,
    finished_trades: 3,
    win_rate_pct: 66.7,
    nifty_same_period_pct: 1.2,
    every_stock_same_period_pct: 0.8,
    enough_trades: false,
    note: 'Too few finished trades to judge — this could be luck.',
  },
  brain_trial: { since: '2026-10-14', finished: 4, needed: 30, sealed: true, sealed_note: 'Sealed until the review.' },
}
const html = (e: EvidenceSummary) => renderToString(<EvidencePanel evidence={e} />)

describe('EvidencePanel', () => {
  it('warns when too few trades', () => {
    expect(html(base)).toContain('Too few finished trades to judge')
    const ok = { ...base, bot: { ...base.bot, enough_trades: true, note: '' } }
    expect(html(ok)).not.toContain('Too few finished trades')
  })
  it('brain part shows only the count and sealed note', () => {
    const h = html(base)
    expect(h).toContain('4 of 30 finished')
    expect(h).toContain('Sealed until the review.')
  })
  it('shows benchmark rows and paper labels', () => {
    const h = html(base)
    expect(h).toContain('NIFTY 50 over the same days')
    expect(h).toContain('Every stock on the watchlist over the same days')
    expect(h.split('Practice money (paper)').length - 1).toBeGreaterThanOrEqual(2)
  })
  it("says the money block is version 1's practice money, without the brain trial", () => {
    const h = html(base)
    expect(h).toContain('Version 1&#x27;s practice money — Practice money (paper)')
    expect(h).toContain('trial is not counted here')
  })
  it('null figures say Not available with a reason, never 0', () => {
    const h = html({
      ...base,
      bot: {
        ...base.bot,
        worst_fall_from_peak_pct: null,
        win_rate_pct: null,
        nifty_same_period_pct: null,
        every_stock_same_period_pct: null,
      },
    })
    expect(h.split('Not available').length - 1).toBe(4)
    expect(h).toContain('needs at least two days of account history')
    expect(h).toContain('no price history for those dates')
  })
})
