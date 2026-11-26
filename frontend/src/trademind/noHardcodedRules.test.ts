// #416: the frontend displays the trading rules; it never owns them. The numbers (+8% target, −4% stop, +5% half,
// 15 trading days) and the holiday list come from GET /config/trading-rules (trademind/tradingRules.ts).
//
// A new literal copy of a rule fails here, naming the file. Rule copies are zero everywhere except the explicit
// allow-list below, which holds text that is not a trading rule in this app, each entry with its reason.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// A rule number as text, the 0.96 / 1.08 price factors, or a holiday list.
// (and the 15% drawdown limit, which is served read-only from the same endpoint)
// Also the 5-session rule (+2%: 0.02) and the research numbers (+6%, −3.5%, 10 days: 0.06, 0.035), written as
// signed percents, as "N% or more", or as a decimal fraction.
const RULE = new RegExp(
  [
    '[+−-]\\s?(8|4|5)(\\.0)?\\s?%',
    '\\b15[- ](trading[- ])?days?\\b',
    '15-trading-day',
    '\\b0\\.96\\b',
    '\\b1\\.08\\b',
    '\\b1\\.05\\b',
    'HOLIDAYS',
    '\\b15\\s?%',
    '[+−-]\\s?(2|6|3\\.5)\\s?%',
    '\\b(2|6)\\s?% or more\\b',
    '\\b0\\.0(2|6|35)\\b',
    '\\b10[- ]trading[- ]days?\\b',
  ].join('|'),
)

/** The files the issue names, plus the ones migrated with them: they read the server's numbers. */
const MIGRATED = [
  'trademind/pages/positionLevels.ts',
  'trademind/pages/PositionParts.tsx',
  'trademind/trackerRules.ts',
  'trademind/brainSteps.ts',
  'trademind/portfolioRules.ts',
  'trademind/today/answerRules.ts',
  'trademind/horizons.ts',
  'trademind/StrategySignals.tsx',
  'trademind/wave3Rules.ts',
  'trademind/vocab.ts',
]

/** Text that states these numbers but is not a trading rule of this app. Lines counted (comments excluded). */
const NOT_RULES: Record<string, { lines: number; reason: string }> = {
  'auth/PublicSite.tsx': {
    lines: 2,
    reason:
      'signed-out marketing copy about our public test portfolio; a visitor has no sign-in, so the page cannot ' +
      'ask the server (two named constants, TEST_PORTFOLIO_FINE and TEST_PORTFOLIO_LONG)',
  },
}

function files(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    return e.isDirectory() ? files(p) : [p]
  })
}

function counts(): Record<string, number> {
  const out: Record<string, number> = {}
  for (const f of files(src)) {
    if (!/\.(ts|tsx|js|jsx)$/.test(f) || /\.(test|spec)\.|test-setup/.test(f)) continue
    const lines = fs.readFileSync(f, 'utf8').replace(/\r\n/g, '\n').split('\n')
    const n = lines.filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l) && RULE.test(l)).length
    if (n) out[path.relative(src, f).replace(/\\/g, '/')] = n
  }
  return out
}

describe('no hardcoded trading rule or holiday list in the frontend (#416)', () => {
  const found = counts()

  it.each(MIGRATED)('%s has no literal copy of a rule number', (file) => {
    expect(found[file] ?? 0).toBe(0)
  })

  it('no file outside the allow-list has a literal copy of a rule', () => {
    const unlisted = Object.keys(found).filter((f) => !(f in NOT_RULES))
    const named = unlisted.map((f) => `${f}: ${found[f]}`)
    expect(named, 'new literal copies of a trading rule (use tradingRules.ts)').toEqual([])
  })

  it('an allow-listed file keeps exactly its listed lines, each with a reason; a stale entry is removed', () => {
    for (const [file, { lines, reason }] of Object.entries(NOT_RULES)) {
      expect(reason.trim().length, `${file} needs a reason`).toBeGreaterThan(20)
      expect(found[file] ?? 0, `${file} has ${found[file] ?? 0} lines; the allow-list says ${lines}`).toBe(lines)
    }
  })

  it.each([
    ['the 15-day plan', 'a +8% target, a −4% stop, half out at +5% in 15 days'],
    ['the 5-session rule', 'closes +2% or more after 5 days'],
    ['the 5-session rule as words', 'does the price close 2% or more higher within 5 days'],
    ['the 5-session rule as a fraction', 'const target = 0.02'],
    ['the 10-session research target', 'a +6% target'],
    ['the 10-session research stop', 'a −3.5% stop'],
    ['the 10-session research fractions', 'const stop = 0.035; const target = 0.06'],
    ['the half-way price factor', 'const half = mid * 1.05'],
    ['a rule with a decimal', "{t1 != null ? '(+5.0%)' : ''}"],
    ['the 10-session window', 'within 10 trading days'],
  ])('the pattern catches %s', (_name, line) => {
    expect(RULE.test(line)).toBe(true)
  })

  it('the holiday list lives only in the backend', () => {
    for (const f of files(src)) {
      if (!/\.(ts|tsx|js|jsx)$/.test(f) || /\.(test|spec)\.|test-setup/.test(f)) continue
      const text = fs.readFileSync(f, 'utf8')
      expect(text.match(/'2026-\d\d-\d\d',\s*'2026-\d\d-\d\d'/), f).toBeNull()
    }
  })
})
