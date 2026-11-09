// Groww Tracker page: renders from the server's numbers (no recomputed status), shows dashes for missing numbers,
// and the menu item can be switched off per browser.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WatchTracker, WatchTrackerItem } from '../api/types'
import { LOOK_KEY } from './look'
import { TRACKER_TAB_KEY, readTrackerTab, writeTrackerTab } from './trackerTab'
import TradeMindApp from './TradeMindApp'

const store = new Map<string, string>()
beforeAll(() => {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
  vi.stubGlobal('window', {
    localStorage: globalThis.localStorage,
    location: { search: '' },
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
  })
})
beforeEach(() => store.clear())

const item = (symbol: string, state: WatchTrackerItem['state'], over: Partial<WatchTrackerItem> = {}): WatchTrackerItem => ({
  symbol, name: `${symbol} Ltd`, added_at: '2026-10-28T05:00:00Z', note: null, buy_price: 4210, entry_price: 4210, entry_source: 'your_price',
  last_price: 4512, return_pct: 7.2, today_pct: 0.7, days_done: 9, score_today: 92, score_prev: 90, score_delta: 2, score_first: 84,
  scores: [84, 86, 90, 92].map((score, i) => ({ date: `2026-10-${28 + i}`, score })),
  closes: [4210, 4262, 4400, 4512].map((close, i) => ({ date: `2026-10-${28 + i}`, close })), state, ...over,
})

const DATA: WatchTracker = {
  as_of: '2026-11-07', horizon_days: 15,
  items: [
    item('KEI', 'target'),
    item('GREENPANEL', 'weak', { return_pct: -6.9, score_today: 54, score_first: 78, score_delta: -4 }),
    item('NEWBIE', 'ok', { buy_price: null, entry_price: null, entry_source: null, last_price: null, return_pct: null, today_pct: null, score_today: null, score_delta: null, scores: [], closes: [], days_done: 0 }),
  ],
}

function render(path: string, data: WatchTracker | undefined) {
  store.set(LOOK_KEY, 'new')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['plan'], { can_see_real_account: false, unrestricted: false, features: [] })
  if (data) client.setQueryData(['myWatchlistTracker'], data)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TradeMindApp ownerConsole={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Groww Tracker page', () => {
  it('shows the act strip, the table and the detail panel from the server data', () => {
    const html = render('/trademind/groww-tracker', DATA)
    expect(html).toContain('data-page="groww-tracker"')
    expect(html).toContain('data-testid="act-strip"')
    expect(html).toContain('data-testid="tracker-table"')
    expect(html).toContain('Reaching target')
    expect(html).toContain('Score falling')
    expect(html).toContain('+7.2%')
    expect(html).toContain('data-testid="tracker-detail"')
    expect(html).toContain('Edit my Groww buy price')
    expect(html).toContain('I sold it in Groww, remove')
    expect(html).toContain('+ Add stock I bought')
    // KEI needs action first, so it is the picked stock
    expect(html).toMatch(/data-testid="tracker-detail" data-symbol="KEI"/)
    expect(html).toContain('₹4,042 / ₹4,547') // stop / target from the entry price
    expect(html).not.toMatch(/NaN|undefined/)
  })

  it('missing numbers show a dash, never NaN', () => {
    const html = render('/trademind/groww-tracker', { ...DATA, items: [DATA.items[2]!] })
    expect(html).toContain('NEWBIE')
    expect(html).toContain('—')
    expect(html).toContain('Add your Groww buy price to see the return chart.')
    expect(html).not.toMatch(/NaN|undefined|null/)
  })

  it('says so in plain English when nothing is followed yet', () => {
    const html = render('/trademind/groww-tracker', { as_of: null, horizon_days: 15, items: [] })
    expect(html).toContain('You are not following any stock yet.')
    expect(html).not.toContain('data-testid="tracker-table"')
  })

  it('shows no table before data arrives', () => {
    const html = render('/trademind/groww-tracker', undefined)
    expect(html).not.toContain('data-testid="act-strip"')
    expect(html).toContain('data-page="groww-tracker"')
  })

  it('menu shows the item by default and a badge when stocks need action', () => {
    const html = render('/trademind/groww-tracker', DATA)
    expect(html).toContain('data-testid="nav-tracker"')
    expect(html).toContain('data-testid="tracker-badge"')
  })

  it('switched off in this browser: the menu hides it, the page still opens and offers to turn it back on', () => {
    store.set(TRACKER_TAB_KEY, 'off')
    const html = render('/trademind/groww-tracker', DATA)
    expect(html).not.toContain('data-testid="nav-tracker"')
    expect(html).toContain('data-testid="tracker-tab-off"')
    expect(html).toContain('Show it in the menu again')
  })

  it('the switch defaults to ON and survives blocked storage', () => {
    expect(readTrackerTab()).toBe(true)
    writeTrackerTab(false)
    expect(readTrackerTab()).toBe(false)
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    })
    expect(readTrackerTab()).toBe(true)
    expect(() => writeTrackerTab(true)).not.toThrow()
  })
})
