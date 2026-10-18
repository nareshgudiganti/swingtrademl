import { describe, expect, it } from 'vitest'
import type { EquityPoint } from '../api/types'
import { BEFORE_TRIAL_NOTE, includesBeforeTrial } from './live-system'

const pt = (before?: boolean): EquityPoint => ({
  date: '2026-09-20',
  total_value: 1,
  cash: 1,
  holdings_value: 0,
  day_pnl: 0,
  drawdown_pct: 0.709,
  open_positions: 0,
  before_trial: before,
})

describe('includesBeforeTrial', () => {
  it('flags a chart that still holds days from before the clean trial', () => {
    expect(includesBeforeTrial([pt(true), pt(false)])).toBe(true)
    expect(BEFORE_TRIAL_NOTE).toContain('Before the clean trial (28 Sep 2026)')
  })
  it('stays quiet for the trial alone or an older server', () => {
    expect(includesBeforeTrial([pt(false)])).toBe(false)
    expect(includesBeforeTrial([pt()])).toBe(false)
  })
})
