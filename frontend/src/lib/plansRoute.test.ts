// oa3: which screen draws the Plans manager. The owner inside TradeMind gets it under Admin > Plans; every other
// way in (the classic /plans URL, the brain switched off, anyone who is not the owner) stays exactly as before:
// the classic light shell, whose own owner check explains why a non-owner cannot use it.
import { describe, expect, it } from 'vitest'

import appSource from '../App.tsx?raw'
import { plansShell } from './plansRoute'

const owner = { isOwner: true, brainEnabled: true, statusFailed: false }

describe('plansShell', () => {
  it('the owner with the brain on gets Plans inside TradeMind at /trademind/plans', () => {
    expect(plansShell('/trademind/plans', owner)).toBe('trademind')
  })

  it('waits for the account status instead of flashing the classic screen first', () => {
    expect(plansShell('/trademind/plans', { ...owner, brainEnabled: undefined })).toBe('wait')
  })

  it('keeps the classic screen when the status could not be read, or the brain is off', () => {
    expect(plansShell('/trademind/plans', { ...owner, brainEnabled: undefined, statusFailed: true })).toBe('classic')
    expect(plansShell('/trademind/plans', { ...owner, brainEnabled: false })).toBe('classic')
  })

  it('keeps the classic screen for anyone who is not the owner (its owner check still answers them)', () => {
    expect(plansShell('/trademind/plans', { ...owner, isOwner: false })).toBe('classic')
    expect(plansShell('/trademind/plans', { isOwner: false, brainEnabled: undefined, statusFailed: false })).toBe('classic')
  })

  it('keeps /plans on the classic screen for everyone, as today', () => {
    for (const p of ['/plans', '/plans/', '/plans/users']) {
      expect(plansShell(p, owner)).toBe('classic')
      expect(plansShell(p, { ...owner, isOwner: false })).toBe('classic')
    }
  })

  it('leaves every other path alone', () => {
    for (const p of ['/trademind', '/trademind/plansx', '/trademind/plans/x', '/home', '/plansx']) {
      expect(plansShell(p, owner)).toBeNull()
    }
  })

  it('is what App.tsx uses', () => {
    expect(appSource).toMatch(/plansShell\(location\.pathname/)
  })
})
