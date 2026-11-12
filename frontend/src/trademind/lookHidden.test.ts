// The Classic look is hidden unless it is switched on (look.ts). While hidden, nothing can select it.
import { afterEach, describe, expect, it, vi } from 'vitest'

import { classicLookEnabled, readLook } from './look'

afterEach(() => vi.unstubAllEnvs())

describe('Classic look switch', () => {
  it('is on in the test build, so the Classic shell stays covered', () => {
    expect(classicLookEnabled()).toBe(true)
    expect(readLook('?look=classic')).toBe('classic')
  })

  it('when hidden, ?look=classic is ignored and the New look is used', () => {
    vi.stubEnv('VITE_CLASSIC_LOOK', '')
    expect(classicLookEnabled()).toBe(false)
    expect(readLook('?look=classic')).toBe('new')
    expect(readLook('')).toBe('new')
  })
})
