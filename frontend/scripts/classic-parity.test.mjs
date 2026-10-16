import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { checkAllowlist, computeParity } from './classic-parity.mjs'

function tree(files) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'parity-'))
  for (const [rel, text] of Object.entries(files)) {
    const full = path.join(root, rel)
    fs.mkdirSync(path.dirname(full), { recursive: true })
    fs.writeFileSync(full, text)
  }
  return root
}

describe('computeParity', () => {
  it('lists the calls a classic page makes that no TradeMind file makes', () => {
    const src = tree({
      'pages/Safety.tsx': 'api.riskEvents(); api.safetyState()',
      'pages/Other.tsx': 'api.status()',
      'trademind/pages/Control.tsx': 'api.safetyState(); api.status()',
    })
    const rows = Object.fromEntries(computeParity(src).map((r) => [r.page, r]))
    expect(rows.Safety.gaps).toEqual(['riskEvents'])
    expect(rows.Other.gaps).toEqual([])
    expect(rows.Safety.calls).toEqual(['riskEvents', 'safetyState'])
  })

  it('counts a call made anywhere under trademind/ (hooks included)', () => {
    const src = tree({ 'pages/A.tsx': 'api.x()', 'trademind/live.ts': 'api.x()' })
    expect(computeParity(src)[0].gaps).toEqual([])
  })
})

describe('computeParity: what it must not get wrong (independent review, 2026-10-16)', () => {
  it('does not count a call that a TradeMind file only mentions in a comment', () => {
    const src = tree({
      'pages/A.tsx': 'api.riskEvents()',
      'trademind/live.ts': '// uses api.riskEvents later\n/* api.riskEvents */\nconst x = 1',
    })
    expect(computeParity(src)[0].gaps).toEqual(['riskEvents'])
  })

  it('still counts a real call on a line that also holds a URL', () => {
    const src = tree({
      'pages/A.tsx': 'api.x()',
      'trademind/live.ts': "const u = 'http://host/y'; api.x()",
    })
    expect(computeParity(src)[0].gaps).toEqual([])
  })

  it('attributes calls made inside a shared component to the classic page that imports it', () => {
    const src = tree({
      'pages/A.tsx': "import Modal from '../components/Modal'\nexport default () => Modal",
      'components/Modal.tsx': 'api.candles()',
      'trademind/live.ts': 'api.status()',
    })
    const row = computeParity(src)[0]
    expect(row.calls).toEqual(['candles'])
    expect(row.gaps).toEqual(['candles'])
  })

  it('credits TradeMind for calls made in a shared component its files import', () => {
    const src = tree({
      'pages/A.tsx': 'api.candles()',
      'components/Chart.tsx': 'api.candles()',
      'trademind/pages/Stock.tsx': "import Chart from '../../components/Chart'\nChart",
    })
    expect(computeParity(src)[0].gaps).toEqual([])
  })

  it('resolves a lib import with and without a file extension, one level only', () => {
    const src = tree({
      'pages/A.tsx': "import { me } from '../lib/plan'",
      'lib/plan.ts': "import { deep } from './deep'\napi.me()",
      'lib/deep.ts': 'api.tooDeep()',
    })
    expect(computeParity(src)[0].calls).toEqual(['me'])
  })

  it('flags api access it cannot read (destructuring, brackets, aliasing) instead of ignoring it', () => {
    const src = tree({
      'pages/A.tsx': "const { riskEvents } = api\napi['other']()\nconst a = api;",
      'trademind/live.ts': 'api.status()',
    })
    const row = computeParity(src)[0]
    expect(row.dynamic.length).toBeGreaterThanOrEqual(3)
    const r = checkAllowlist([row], {}, { strict: false })
    expect(r.unexplained).toContainEqual({ page: 'A', call: '<dynamic api access>' })
    expect(r.ok).toBe(false)
  })

  it('does not flag ordinary words that merely contain "api"', () => {
    const src = tree({ 'pages/A.tsx': 'const rapid = 1; const capital = rapid; // api = x', 'trademind/live.ts': '' })
    expect(computeParity(src)[0].dynamic).toEqual([])
  })
})

describe('checkAllowlist', () => {
  const parity = [
    { page: 'Capital', lines: 1, calls: ['riskEvents'], gaps: ['riskEvents'] },
    { page: 'Models', lines: 1, calls: ['train', 'mystery'], gaps: ['train', 'mystery'] },
    { page: 'Finance', lines: 1, calls: ['a', 'b'], gaps: ['a', 'b'] },
  ]
  const allow = {
    Capital: { riskEvents: { status: 'planned', task: 'oa2' } },
    Models: { train: { status: 'v2', decision: 'owner 2026-10-04' } },
    Finance: { '*': { status: 'separate_app' } },
  }

  it('fails on a gap nobody explained', () => {
    const r = checkAllowlist(parity, allow, { strict: false })
    expect(r.unexplained).toEqual([{ page: 'Models', call: 'mystery' }])
    expect(r.ok).toBe(false)
  })

  it('passes when every gap is explained, treating planned as acceptable', () => {
    const ok = checkAllowlist(parity, { ...allow, Models: { train: { status: 'v2', decision: 'owner 2026-10-04' }, mystery: { status: 'deferred', decision: 'oa4' } } }, { strict: false })
    expect(ok.unexplained).toEqual([])
    expect(ok.planned).toEqual([{ page: 'Capital', call: 'riskEvents', task: 'oa2', status: 'planned' }])
    expect(ok.ok).toBe(true)
  })

  it('strict mode (the deletion gate) fails while anything is still only planned', () => {
    const a = { ...allow, Models: { train: { status: 'v2', decision: 'owner 2026-10-04' }, mystery: { status: 'deferred', decision: 'oa4' } } }
    expect(checkAllowlist(parity, a, { strict: true }).ok).toBe(false)
    const done = { ...a, Capital: { riskEvents: { status: 'v2', decision: 'owner' } } }
    expect(checkAllowlist(parity, done, { strict: true }).ok).toBe(true)
  })

  it('a "*" entry explains every call of a page (the separate Finance app)', () => {
    expect(checkAllowlist(parity.slice(2), allow, { strict: true }).ok).toBe(true)
  })

  it('v2 and deferred only count when they cite an owner decision', () => {
    const p = [{ page: 'Models', lines: 1, calls: ['train'], gaps: ['train'] }]
    expect(checkAllowlist(p, { Models: { train: { status: 'v2' } } }, { strict: false }).unexplained).toEqual([{ page: 'Models', call: 'train' }])
    const cited = { Models: { train: { status: 'v2', decision: 'owner 2026-10-04: no create/delete/train until v2' } } }
    expect(checkAllowlist(p, cited, { strict: true }).ok).toBe(true)
  })

  it('decide and keep are acceptable now but fail the strict deletion gate', () => {
    const p = [{ page: 'Models', lines: 1, calls: ['activateModel'], gaps: ['activateModel'] }]
    const decide = { Models: { activateModel: { status: 'decide', task: 'oa15' } } }
    expect(checkAllowlist(p, decide, { strict: false }).ok).toBe(true)
    expect(checkAllowlist(p, decide, { strict: true }).ok).toBe(false)
    const keep = { Models: { activateModel: { status: 'keep', task: 'oa10' } } }
    expect(checkAllowlist(p, keep, { strict: true }).ok).toBe(false)
  })

  it('rejects an unknown status, so a typo cannot hide a gap', () => {
    const r = checkAllowlist(parity.slice(0, 1), { Capital: { riskEvents: { status: 'later' } } }, { strict: false })
    expect(r.ok).toBe(false)
    expect(r.unexplained).toEqual([{ page: 'Capital', call: 'riskEvents' }])
  })
})

describe('the real tree', () => {
  it('has no unexplained classic-only call (new gaps must be added to the allow-list on purpose)', () => {
    const here = path.dirname(fileURLToPath(import.meta.url))
    const parity = computeParity(path.join(here, '..', 'src'))
    const allow = JSON.parse(fs.readFileSync(path.join(here, 'classic-parity-allowlist.json'), 'utf8'))
    expect(parity.length).toBeGreaterThan(10)
    const r = checkAllowlist(parity, allow, { strict: false })
    expect(r.unexplained).toEqual([])
  })
})
