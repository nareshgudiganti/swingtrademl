// #310 slice A: saved screens. Restore (A1), a value that is gone is shown and never substituted (A6), the digest
// panel states (loading, locked, not enough history, normal, data not fresh), and no promise of gain (A9).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import type { BrainDecision } from '../api/types'
import ChangesPanel, { ChangesView, LOCKED_TEXT } from './ChangesPanel'
import { filterIdeas } from './discoverRules'
import SavedScreensBar from './SavedScreensBar'
import {
  applyExtras,
  controlsFromSpec,
  describeSpec,
  listBlocked,
  placeText,
  sameAsSaved,
  screenProblems,
  specFromControls,
  type DigestRow,
  type ScreenDigest,
  type ScreenSpec,
} from './savedScreens'

beforeAll(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
})

const spec = (over: Partial<ScreenSpec> = {}): ScreenSpec => ({
  horizon: '15d', cap_tiers: [], patterns: [], word: 'ALL', sector: null, query: '', layout: 'table', watch_only: false, ...over,
})

const idea = (symbol: string, word: string) => ({ symbol, word, overruled_word: null }) as unknown as BrainDecision

describe('restoring a saved screen (A1)', () => {
  it('puts every control back, and the list equals the one the same hand-set filters give', () => {
    const ideas = [idea('KEI', 'TRADE'), idea('INFY', 'WATCH'), idea('KEC', 'TRADE'), idea('TCS', 'AVOID')]
    const sectorOf = { KEI: 'Capital goods', KEC: 'Capital goods', INFY: 'IT', TCS: 'IT' }
    const handSet = { filter: 'TRADE' as const, sector: 'Capital goods', query: 'ke', layout: 'slides' as const }
    const saved = specFromControls(handSet)
    // what was saved round-trips through the server as plain JSON
    const restored = controlsFromSpec(JSON.parse(JSON.stringify(saved)))
    expect(restored).toEqual(handSet)
    const a = filterIdeas(ideas, { filter: handSet.filter, sector: handSet.sector, query: handSet.query, sectorOf })
    const b = filterIdeas(ideas, { filter: restored.filter, sector: restored.sector, query: restored.query, sectorOf })
    expect(b.map((d) => d.symbol)).toEqual(a.map((d) => d.symbol))
    expect(b.map((d) => d.symbol)).toEqual(['KEI', 'KEC'])
  })

  it('keeps the fields Discover has no control for when a screen is updated', () => {
    const base = spec({ cap_tiers: ['large'], watch_only: true })
    const next = specFromControls({ filter: 'WATCH', sector: '', query: ' kei ', layout: 'table' }, base)
    expect(next).toMatchObject({ cap_tiers: ['large'], watch_only: true, word: 'WATCH', sector: null, query: 'kei' })
    expect(sameAsSaved(base, { filter: 'ALL', sector: '', query: '', layout: 'table' })).toBe(true)
    expect(sameAsSaved(base, { filter: 'WAIT', sector: '', query: '', layout: 'table' })).toBe(false)
  })

  it('reads the saved company-size and watchlist-only filters', () => {
    const ideas = [idea('AAA', 'TRADE'), idea('BBB', 'TRADE')]
    const tier = (s: string) => (s === 'AAA' ? 'large' : 'smallcap')
    expect(applyExtras(ideas, spec({ cap_tiers: ['large'] }), { tierOf: tier, watch: null }).map((d) => d.symbol)).toEqual(['AAA'])
    expect(applyExtras(ideas, spec({ watch_only: true }), { tierOf: tier, watch: new Set(['BBB']) }).map((d) => d.symbol)).toEqual(['BBB'])
    expect(applyExtras(ideas, spec({ watch_only: true }), { tierOf: tier, watch: null })).toEqual([])
  })
})

describe('a saved value that is gone is shown, never substituted (A6)', () => {
  it('names a missing sector, an unknown window, an unknown word and a pattern filter', () => {
    expect(screenProblems(spec({ sector: 'Telecom' }), ['IT'])).toEqual(['The sector “Telecom” is no longer available.'])
    expect(screenProblems(spec({ sector: 'IT' }), ['IT'])).toEqual([])
    expect(screenProblems(spec({ sector: 'Telecom' }), null)).toEqual([]) // not judged while the sector map is unknown
    expect(screenProblems(spec({ horizon: '7d' }), null)[0]).toContain('no longer available')
    expect(screenProblems(spec({ word: 'HOLD' }), null)[0]).toContain('no longer available')
    expect(screenProblems(spec({ patterns: ['base'] }), null)[0]).toContain('not available on this list yet')
  })

  it('an unavailable window, unknown word or pattern empties the list instead of showing another', () => {
    expect(listBlocked(spec())).toBe(false)
    expect(listBlocked(spec({ horizon: '5d' }))).toBe(true)
    expect(listBlocked(spec({ horizon: '7d' }))).toBe(true)
    expect(listBlocked(spec({ word: 'HOLD' }))).toBe(true)
    expect(listBlocked(spec({ patterns: ['base'] }))).toBe(true)
    expect(screenProblems(spec({ horizon: '5d' }), null)[0]).toMatch(/nothing to show/)
  })

  it('a sector that is gone matches no stock', () => {
    const ideas = [idea('KEI', 'TRADE')]
    expect(filterIdeas(ideas, { filter: 'ALL', sector: 'Telecom', sectorOf: { KEI: 'Capital goods' } })).toEqual([])
  })
})

describe('plain wording', () => {
  it('reads the filters back in words, with BUY for TRADE', () => {
    expect(describeSpec(spec())).toMatch(/every stock/)
    const text = describeSpec(spec({ cap_tiers: ['large'], word: 'TRADE', sector: 'IT', query: 'kei', watch_only: true }))
    expect(text).toContain('Large companies')
    expect(text).toContain('BUY')
    expect(text).not.toContain('TRADE')
    expect(text).toContain('matching “kei”')
    expect(text).toContain('my watchlist only')
  })

  it('writes a place in the ranking, never a score', () => {
    expect(placeText(3, 120)).toBe('3rd of 120')
    expect(placeText(1, 2)).toBe('1st of 2')
    expect(placeText(11, 20)).toBe('11th of 20')
    expect(placeText(22, 30)).toBe('22nd of 30')
    expect(placeText(null, 5)).toBeNull()
  })
})

const row = (symbol: string, reason: string, code = 'word_changed', now = 'TRADE', before = 'WAIT'): DigestRow => ({
  symbol, reason, reason_code: code, rank: 3, rank_of: 120,
  now: { word: now, rank: 3, rank_of: 120 }, before: { word: before, rank: 9, rank_of: 118 },
})

const digest = (over: Partial<ScreenDigest> = {}): ScreenDigest => ({
  comparable: true, note: null,
  current: { run_id: 'a', day: '2026-11-27', as_of: '', banner_mode: 'NORMAL' },
  previous: { run_id: 'b', day: '2026-11-26', as_of: '', banner_mode: 'NORMAL' },
  came_in: [], dropped_out: [], not_compared: [],
  footer: 'This is a ranking among the stocks the brain checked that night. It is not a chance of profit and not advice.',
  ...over,
})

describe('the what-changed panel', () => {
  it('lists came in and dropped out with one reason each, the place and the word move', () => {
    const html = renderToString(
      <ChangesView
        digest={digest({
          came_in: [row('KEI', 'The brain moved it from WAIT to BUY.')],
          dropped_out: [row('TCS', 'The brain moved it from BUY to WATCH.', 'word_changed', 'WATCH', 'TRADE')],
        })}
      />,
    )
    expect(html).toContain('Came in')
    expect(html).toContain('Dropped out')
    expect(html).toContain('KEI')
    expect(html).toContain('WAIT → BUY')
    expect(html).toContain('3rd of 120')
    expect(html).toContain('The brain moved it from BUY to WATCH.')
    expect(html).toContain('data-testid="digest-footer"')
    expect(html).not.toContain('TRADE') // the app says BUY
  })

  it('says there is not enough history and lists nothing', () => {
    const html = renderToString(<ChangesView digest={digest({ comparable: false, note: 'There is no earlier nightly run.', current: null, previous: null })} />)
    expect(html).toContain('Not enough scan history yet to say what changed.')
    expect(html).not.toContain('digest-came-in')
  })

  it('shows a stock with data that is not fresh under its own heading, never under Came in', () => {
    const html = renderToString(
      <ChangesView digest={digest({ not_compared: [row('OLD', 'Data not fresh, not compared.', 'data_not_fresh')] })} />,
    )
    expect(html).toContain('Not compared')
    expect(html).toContain('Data not fresh, not compared.')
    expect(html).not.toContain('data-testid="digest-came-in"')
  })

  it('says plainly when nothing changed', () => {
    expect(renderToString(<ChangesView digest={digest()} />)).toContain('Nothing came in or dropped out')
  })

  it('never promises gain', () => {
    const html = renderToString(<ChangesView digest={digest({ came_in: [row('KEI', 'Now matches your pattern filter.')] })} />)
    const text = html.replace(/<[^>]+>/g, ' ').replace('not a chance of profit', '')
    expect(text).not.toMatch(/profit|return|gain|will rise|likely/i)
  })

  function panel(plan: object, data?: ScreenDigest) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(['plan'], plan)
    if (data) client.setQueryData(['screenDigest', 7], data)
    return renderToString(
      <QueryClientProvider client={client}>
        <ChangesPanel screenId={7} />
      </QueryClientProvider>,
    )
  }
  // usePlan only reads the plan when a sign-in token exists; here it has none, so the Free path is the safe default.
  it('a Free account gets one plain line instead of the note', () => {
    const html = panel({ unrestricted: false, features: ['picks'] })
    expect(html).toContain(LOCKED_TEXT)
    expect(html).not.toContain('digest-came-in')
  })
})

describe('the Saved screens menu', () => {
  it('renders the menu, the save button and the read-back area at rest', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(['savedScreens'], {
      screens: [{ id: 1, name: 'Large BUY', spec: spec({ word: 'TRADE' }), filters_version: 1, created_at: null, updated_at: null }],
      limit: 3,
    })
    const html = renderToString(
      <QueryClientProvider client={client}>
        <SavedScreensBar
          controls={{ filter: 'ALL', sector: '', query: '', layout: 'table' }}
          active={null}
          problems={[]}
          onOpen={() => {}}
          onClose={() => {}}
        />
      </QueryClientProvider>,
    )
    expect(html).toContain('data-testid="saved-screens-menu"')
    expect(html).toContain('Large BUY')
    expect(html).toContain('Save current filters')
    expect(html.replace(/<!-- -->/g, '')).toContain('1 of 3 saved')
  })

  it('shows the opened screen, what it shows and what is no longer available', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const s = { id: 1, name: 'Old sector', spec: spec({ sector: 'Telecom' }), filters_version: 1, created_at: null, updated_at: null }
    client.setQueryData(['savedScreens'], { screens: [s], limit: 3 })
    const html = renderToString(
      <QueryClientProvider client={client}>
        <SavedScreensBar
          controls={{ filter: 'ALL', sector: 'Telecom', query: '', layout: 'table' }}
          active={s}
          problems={screenProblems(s.spec, ['IT'])}
          onOpen={() => {}}
          onClose={() => {}}
        />
      </QueryClientProvider>,
    )
    expect(html).toContain('Showing: ')
    expect(html).toContain('Telecom')
    expect(html).toContain('no longer available')
    expect(html).toContain('Rename')
    expect(html).toContain('Delete')
  })
})
