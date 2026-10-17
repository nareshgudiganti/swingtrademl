import { describe, expect, it } from 'vitest'

import { DEFAULT_HORIZON, HORIZONS, VALIDATION_TEXT, horizonById } from './horizons'

describe('trading horizons (owner decision 17 Oct, Phase 3a)', () => {
  it('lists 1, 5, 15, 30 and 90 trading days, in that order', () => {
    expect(HORIZONS.map((h) => h.days)).toEqual([1, 5, 15, 30, 90])
  })

  it('defaults to 15 days', () => {
    expect(DEFAULT_HORIZON).toBe('15d')
    expect(horizonById(DEFAULT_HORIZON).days).toBe(15)
  })

  it('only 15 days has a supported trading strategy', () => {
    expect(HORIZONS.filter((h) => h.available).map((h) => h.days)).toEqual([15])
  })

  it('keeps availability and validation as two separate labels', () => {
    for (const h of HORIZONS) {
      expect(h.availabilityText.length).toBeGreaterThan(0)
      if (h.available) expect(h.validation).not.toBeNull()
      else expect(h.validation).toBeNull()
    }
  })

  it('labels the 15-day strategy "Experimental, unproven"', () => {
    const h = horizonById('15d')
    expect(h.validation).toBe('experimental')
    expect(VALIDATION_TEXT.experimental).toBe('Experimental, unproven')
  })

  it('never labels anything "Validated" today', () => {
    expect(HORIZONS.some((h) => h.validation === 'validated')).toBe(false)
  })

  it('every unsupported horizon says "No supported trading strategy"', () => {
    for (const h of HORIZONS.filter((x) => !x.available)) {
      expect(h.availabilityText).toBe('No supported trading strategy')
    }
  })

  it('marks the 5-day predictions as research, unvalidated and not a trading plan', () => {
    const note = horizonById('5d').research ?? ''
    expect(note).toMatch(/research/i)
    expect(note).toMatch(/unvalidated/i)
    expect(note).toMatch(/not a trading plan/i)
    for (const h of HORIZONS.filter((x) => x.days !== 5)) expect(h.research).toBeUndefined()
  })
})
