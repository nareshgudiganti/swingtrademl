// #416: no module may read a trading rule at import time. The screens render only after the server numbers are
// loaded (TradingRulesGate), but a module-level call such as `const X = plan().days` runs when the file is first
// imported, before anything is loaded, and would crash the app on start.
//
// Every source module is imported on a fresh module graph with NO rules loaded; a module that asks for a rule
// then fails here, naming the file. (Other import errors, such as a browser-only API in a node test, are not
// this test's business and are ignored.)
import { describe, expect, it, vi } from 'vitest'

const loaders = import.meta.glob(
  [
    '../**/*.{ts,tsx}',
    '!../**/*.{test,spec}.*',
    '!../**/*.d.ts',
    '!../main.tsx',
    '!../test-setup.ts',
  ],
  { eager: false },
)

describe('importing a module never reads a trading rule (#416)', () => {
  it('finds the source tree it is meant to check', () => {
    expect(Object.keys(loaders).length).toBeGreaterThan(100)
    expect(Object.keys(loaders).some((f) => f.endsWith('/horizons.ts'))).toBe(true)
    expect(Object.keys(loaders).some((f) => f.endsWith('/App.tsx'))).toBe(true)
  })

  it('every module imports with the rules cleared', async () => {
    vi.resetModules() // a fresh graph: tradingRules.ts starts with nothing loaded
    const { tradingRulesLoaded } = await import('./tradingRules')
    expect(tradingRulesLoaded()).toBe(false)
    const offenders: string[] = []
    for (const [file, load] of Object.entries(loaders)) {
      try {
        await load()
      } catch (error) {
        if (/trading rules are not loaded/i.test(String((error as Error)?.message))) offenders.push(file)
      }
    }
    expect(offenders, 'modules that read a trading rule when imported').toEqual([])
  }, 120_000)
})
