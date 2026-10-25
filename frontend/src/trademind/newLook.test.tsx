// The two looks (look.ts): classic stays the default, the new look renders at every URL for the owner and everyone
// else with the same menu rules, and the new Today says only what the run says.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { BrainDecision, BrainRun } from '../api/types'
import { LOOK_KEY, readLook } from './look'
import { SECTIONS } from './menu'
import { greeting, oneReason, safetySummary, stoppedByRoom, todayHeadline } from './today/answerRules'
import { brainSteps, NOT_RECORDED, stopOf } from './brainSteps'
import { activeNav, navPages, visibleNav } from './newMenu'
import TradeMindApp from './TradeMindApp'

const store = new Map<string, string>()
beforeAll(() => {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
  // look.ts reads window.localStorage / window.location; plain Node has no window.
  vi.stubGlobal('window', {
    localStorage: globalThis.localStorage,
    location: { search: '' },
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
  })
})
beforeEach(() => store.clear())

let nextId = 1
const dec = (symbol: string, word: string, confidence: number, over: Partial<BrainDecision> = {}): BrainDecision =>
  ({
    id: nextId++, run_id: 'r1', symbol, kind: 'idea', word, reasons: [`${symbol} reason`], entry_low: 100,
    entry_high: 102, target: 108, stop: 96, qty: 0, horizon_days: 15, confidence, honest_score: null,
    evidence_text: null, downgraded_from: null, downgrade_reason: null, overruled_word: null, overrule_reason: null,
    overruled_by: null, overruled_at: null, ...over,
  }) as BrainDecision

const RUN = {
  run_id: 'r1', kind: 'nightly', as_of: '2026-10-22', live: true, ms: 1, error: null, counts: {}, status: 'done',
  started_at: '2026-10-22T13:20:00Z', banner: { mode: 'DEFENSIVE', headline: 'Weak market today.' }, book: 'bot',
  modules: {}, quality: { overall: null, stale: [] }, sectors: [], situations: [], portfolio: {},
  decisions: [
    dec('AAAWATCH', 'WATCH', 0.8),
    dec('BBBROOM', 'WAIT', 0.7, { reasons: ['risk check said no: no room in the account'] }),
    dec('HELDFLAG', 'EXIT', 0.5, { kind: 'holding', reasons: ['Fell below its stop.'] }),
  ],
} as unknown as BrainRun

function render(path: string, owner: boolean, withRun = false): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['plan'], { can_see_real_account: owner, unrestricted: owner, features: [] })
  if (withRun) client.setQueryData(['brainLatest', 'nightly'], RUN)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TradeMindApp ownerConsole={owner} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the look switch', () => {
  it('is classic unless the viewer chose otherwise', () => {
    expect(readLook('')).toBe('classic')
    store.set(LOOK_KEY, 'something-else')
    expect(readLook('')).toBe('classic')
  })

  it('remembers the new look, and ?look= in the address wins and is remembered', () => {
    store.set(LOOK_KEY, 'new')
    expect(readLook('')).toBe('new')
    expect(readLook('?look=classic')).toBe('classic')
    expect(store.get(LOOK_KEY)).toBe('classic')
  })

  it('the classic look is unchanged and offers the new look (on the bar for members, in the account menu for the owner)', () => {
    const member = render('/trademind', false)
    expect(member).toContain('tm-topbar')
    expect(member).not.toContain('tmn-side')
    expect(member).toContain('data-testid="look-switch"')
    expect(render('/trademind', true)).not.toContain('class="tm-look-switch"') // the owner's bar keeps its room
  })
})

describe('the new look renders at every URL', () => {
  const paths = [...new Set(['/trademind', ...SECTIONS.flatMap((s) => s.pages.map((p) => p.to)), '/trademind/stock/INFY'])]
  for (const owner of [true, false]) {
    it.each(paths)(`${owner ? 'owner' : 'non-owner'}: %s`, (path) => {
      store.set(LOOK_KEY, 'new')
      const html = render(path, owner)
      expect(html).toContain('tmn-side')
      expect(html).toContain('Classic look') // the way back is always there
      expect(html.includes('nav-admin')).toBe(owner)
    })
  }

  it('the non-owner never sees the real Zerodha tab', () => {
    store.set(LOOK_KEY, 'new')
    expect(render('/trademind/positions', false)).not.toContain('My Zerodha')
  })
})

describe('the new Today', () => {
  it('answers first: headline, top ideas with AI analysis links, safety line, no old dump', () => {
    store.set(LOOK_KEY, 'new')
    const html = render('/trademind', false, true)
    expect(html).toContain('data-testid="today-headline"')
    expect(html).toContain('Careful market: no new trades today. 1 stock to watch, 1 holding needs a look.')
    expect(html).not.toContain('data-page="today"') // no old Today dump under the answer
    expect(html).toContain('data-testid="safety-line"')
    expect(html).toContain('AI analysis →')
    expect(html).toContain('stopped by the account')
    expect(html).not.toMatch(/\d+%\s*chance/i)
  })

  it('headline wording', () => {
    const c = (TRADE: number, WATCH: number) => ({ TRADE, WATCH, WAIT: 0, AVOID: 0 })
    expect(todayHeadline('NORMAL', c(2, 0), 0)).toBe('2 new trade ideas today.')
    expect(todayHeadline('NORMAL', c(1, 3), 2)).toBe('1 new trade idea today. 3 stocks to watch, 2 holdings need a look.')
    expect(todayHeadline('NO_NEW_TRADES', c(0, 0), 0)).toMatch(/^No new trades today: /)
    expect(todayHeadline(null, c(0, 0), 0)).toBe('No new trades today.')
  })

  it('counts room-blocked ideas and gives one plain reason, never a raw score', () => {
    expect(stoppedByRoom(RUN.decisions)).toBe(1)
    expect(oneReason(RUN.decisions[1]!)).toMatch(/safety limits had no room/)
    expect(oneReason(dec('X', 'TRADE', 0.9, { reasons: ['Model score 82% and rising'] }))).not.toContain('%')
  })

  it('greets by the hour in India', () => {
    expect(greeting(new Date('2026-10-24T03:00:00Z'))).toBe('Good morning') // 08:30 IST
    expect(greeting(new Date('2026-10-24T09:00:00Z'))).toBe('Good afternoon') // 14:30 IST
    expect(greeting(new Date('2026-10-24T14:00:00Z'))).toBe('Good evening') // 19:30 IST
  })
})

describe('the 8-item menu', () => {
  it('owner sees 8 items, everyone else all but Admin (wave 2: everyone has their own watchlist)', () => {
    expect(visibleNav(true).map((n) => n.id)).toEqual(['today', 'discover', 'portfolio', 'watchlist', 'market', 'evidence', 'history', 'admin'])
    expect(visibleNav(false).map((n) => n.id)).toEqual(['today', 'discover', 'portfolio', 'watchlist', 'market', 'evidence', 'history'])
  })

  it('a stock page belongs to Discover; owner-only and real pages stay hidden', () => {
    expect(activeNav('/trademind/stock/INFY', false).id).toBe('discover')
    expect(activeNav('/trademind/control', false).id).toBe('today') // admin is never highlighted for a non-owner
    const portfolio = visibleNav(false).find((n) => n.id === 'portfolio')!
    expect(navPages(portfolio, false, { realAccount: false }).map((p) => p.label).join()).not.toMatch(/Zerodha|Testing/)
  })

  it('renders the new stock page with the 8 steps for a stock in the run', () => {
    store.set(LOOK_KEY, 'new')
    const html = render('/trademind/stock/BBBROOM', false, true)
    expect(html).toContain('data-testid="brain-steps"')
    expect(html).toContain('Stopped here')
    expect(html).toContain('Chart, company and news')
  })
})

describe('the brain steps for one stock', () => {
  const steps = (d: BrainDecision) => brainSteps(d, RUN)

  it('a room-blocked idea stops at step 6; nothing after it is invented', () => {
    const d = RUN.decisions[1]!
    expect(stopOf(d)?.step).toBe(6)
    const s = steps(d)
    expect(s).toHaveLength(8)
    expect(s[5]).toMatchObject({ n: 6, state: 'stop', tag: 'Stopped here' })
    expect(s[6]).toMatchObject({ n: 7, state: 'word', tag: 'WAIT' })
    expect(s[7]).toMatchObject({ n: 8, state: 'later' })
  })

  it('below the buy level stops at step 5; the safety step after it says not recorded', () => {
    const d = dec('LOWSCORE', 'WAIT', 0.3, { reasons: ['Model score 30% is below the buy level 60%.'] })
    const s = steps(d)
    expect(s[4]!.state).toBe('stop')
    expect(s[5]).toMatchObject({ state: 'none', line: NOT_RECORDED })
    expect(s.map((x) => x.line).join(' ')).not.toMatch(/\d+%\s*chance/i)
  })

  it('a TRADE passes the safety check and has no stop', () => {
    const d = dec('GOOD', 'TRADE', 0.9, { reasons: ['Strong trend'] })
    expect(stopOf(d)).toBeNull()
    expect(steps(d)[5]).toMatchObject({ state: 'ok', tag: 'PASSED' })
  })
})

describe('the safety line', () => {
  it('states only numbers the server gave', () => {
    expect(safetySummary({ owner: false, ddPct: 5, haltPct: 15 }).text).toMatch(/−4% stop/)
    expect(safetySummary({ owner: true, ddPct: 2.1, haltPct: 15 }).text).toBe('Safety net on. The account is 2.1% below its peak — new buys stop at 15%.')
    expect(safetySummary({ owner: true, ddPct: 16, haltPct: 15 }).tone).toBe('bad')
    expect(safetySummary({ owner: true, paused: true, ddPct: null, haltPct: null }).tone).toBe('bad')
  })
})
