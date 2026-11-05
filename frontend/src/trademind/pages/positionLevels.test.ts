import { describe, expect, it } from 'vitest'

import { barPercent, levelFor } from './positionLevels'

describe('where a position sits between stop, half-profit and target', () => {
  it.each([
    [-4.5, 'stop'],
    [-3.5, 'near_stop'],
    [-1, 'hold'],
    [4.2, 'near_half'],
    [5.2, 'half'],
    [7.3, 'near_target'],
    [8.1, 'target'],
  ])('%s%% is %s', (ret, state) => {
    expect(levelFor(ret).state).toBe(state)
  })

  it('only quiet positions are not "act today"', () => {
    expect(levelFor(0.5).act).toBe(false)
    expect(levelFor(0.5, true).state).toBe('watch')
    expect(levelFor(-3.5).act).toBe(true)
  })

  it('puts the dot on the -4%..+8% bar and clamps it', () => {
    expect(barPercent(-4)).toBe(0)
    expect(barPercent(8)).toBe(100)
    expect(barPercent(2)).toBe(50)
    expect(barPercent(20)).toBe(100)
  })
})
