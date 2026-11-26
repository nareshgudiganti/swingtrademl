import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import adminSource from './AdminUsers.tsx?raw'
import pageSource from './AdminCandles.tsx?raw'
import { CandleLogView, type CandleLog } from './AdminCandles'

const DATA: CandleLog = {
  window_days: 30,
  late_rule: 'A day’s price bar is late when it first reached us after 09:15 IST on the next trading day.',
  unknown_note: 'Bars stored before arrival times were recorded have no arrival time, so they are not listed.',
  late_total: 1,
  late: [
    {
      symbol: 'KEI',
      day: '2026-11-25',
      due_by: '2026-11-26T09:15:00+05:30',
      received_at: '2026-11-26T10:00:00+05:30',
      late_by_hours: 0.8,
    },
  ],
  corrections: [
    {
      symbol: 'HUL',
      day: '2026-11-26',
      corrected_at: '2026-11-26T19:30:00+05:30',
      old_close: 100,
      new_close: 102,
      close_change_pct: 0.02,
      old_volume: 10,
      new_volume: 12,
    },
  ],
}

describe('admin late and corrected prices (#565)', () => {
  it('is a tab of the admin screen and calls only the read route', () => {
    expect(adminSource).toContain('<AdminCandles')
    expect(pageSource).toContain("'/admin/console/candle-log'")
    expect(pageSource).not.toMatch(/method:\s*'(PUT|POST|DELETE|PATCH)'/)
  })
  it('shows the rule, the late bar on its India day and the before/after of a correction', () => {
    const html = renderToStaticMarkup(<CandleLogView data={DATA} />)
    expect(html).toContain('09:15 IST')
    expect(html).toContain('KEI')
    expect(html).toContain('25 Nov 2026')
    expect(html).toContain('0.8 hours')
    expect(html).toContain('₹100 → ₹102')
    expect(html).toContain('+2.00%')
    expect(html).not.toContain('<button')
  })
  it('says so plainly when there is nothing to show', () => {
    const html = renderToStaticMarkup(<CandleLogView data={{ ...DATA, late: [], late_total: 0, corrections: [] }} />)
    expect(html).toContain('No late prices in this period.')
    expect(html).toContain('No corrected prices in this period.')
  })
})
