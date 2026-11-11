// Groww Tracker page: renders from the server's numbers (no recomputed status), shows dashes for missing numbers,
// and the menu item can be switched off per browser.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WatchTracker, WatchTrackerItem } from '../api/types'
import { LOOK_KEY } from './look'
import { TRACKER_TAB_KEY, readTrackerTab, writeTrackerTab } from './trackerTab'
import { EditableRow } from './pages/GrowwTracker'
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
  symbol, name: `${symbol} Ltd`, added_at: '2026-10-28T05:00:00Z', note: null, buy_price: 4210, bought_on: '2026-10-28', quantity: 10, invested: 42100,
  profit_amount: 3020, entry_price: 4210, entry_source: 'your_price',
  last_price: 4512, return_pct: 7.2, today_pct: 0.7, days_done: 9, score_today: 92, score_prev: 90, score_delta: 2, score_first: 84,
  scores: [84, 86, 90, 92].map((score, i) => ({ date: `2026-10-${28 + i}`, score })),
  closes: [4210, 4262, 4400, 4512].map((close, i) => ({ date: `2026-10-${28 + i}`, close })), state, ...over,
})

const DATA: WatchTracker = {
  as_of: '2026-11-07', horizon_days: 15,
  items: [
    item('KEI', 'target'),
    item('GREENPANEL', 'weak', { return_pct: -6.9, score_today: 54, score_first: 78, score_delta: -4 }),
    item('NEWBIE', 'ok', { quantity: null, invested: null, profit_amount: null, buy_price: null, entry_price: null, entry_source: null, last_price: null, return_pct: null, today_pct: null, score_today: null, score_delta: null, scores: [], closes: [], days_done: 0 }),
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
    // The Sold records chip sits right after the last filter chip
    expect(html).toContain('data-testid="sold-chip"')
    expect(html.indexOf('data-testid="sold-chip"')).toBeGreaterThan(html.lastIndexOf('>Score falling</button>'))
    expect(html).toContain('+7.2%')
    expect(html).toContain('data-testid="tracker-detail"')
    // An Edit button on every row and one in the detail panel; the old separate price / note buttons are gone.
    expect(html).toContain('data-testid="edit-KEI"')
    expect(html).toContain('data-testid="edit-GREENPANEL"')
    expect(html).toContain('data-testid="edit-NEWBIE"')
    expect(html).toContain('data-testid="detail-edit"')
    expect(html).not.toContain('Edit my Groww buy price')
    expect(html).not.toContain('Add a note')
    // Bought on, shares, invested and profit in rupees come from the server
    expect(html).toContain('data-testid="fact-bought-on"')
    expect(html).toContain('₹42,100')
    expect(html).toContain('+₹3,020')
    expect(html).toContain('I sold it in Groww')
    expect(html).toContain('+ Add stock I bought')
    // KEI needs action first, so it is the picked stock
    expect(html).toMatch(/data-testid="tracker-detail" data-symbol="KEI"/)
    expect(html).toContain('₹4,042 (−4%) / ₹4,547 (+8%)') // stop / target from the entry price
    expect(html).not.toMatch(/NaN|undefined/)
  })

  it('missing numbers show a dash, never NaN', () => {
    const html = render('/trademind/groww-tracker', { ...DATA, items: [DATA.items[2]!] })
    expect(html).toContain('NEWBIE')
    expect(html).toContain('—')
    expect(html).toContain('Add your Groww buy price to see the return chart.')
    expect(html).not.toMatch(/NaN|undefined|null/)
  })

  it('without shares the rupee facts are dashes and the page offers to add them', () => {
    const html = render('/trademind/groww-tracker', { ...DATA, items: [DATA.items[2]!] })
    expect(html).toContain('Add your shares to see profit and loss in rupees.')
    expect(html).not.toMatch(/NaN|undefined/)
  })

  it('the table has Bought on, Price paid and Shares columns that show the saved values or a dash', () => {
    const html = render('/trademind/groww-tracker', DATA)
    expect(html).toContain('>Bought on<')
    expect(html).toContain('>Price paid<')
    expect(html).toContain('>Shares<')
    expect(html).toMatch(/data-testid="bought-KEI"[^>]*>28 Oct 2026</)
    expect(html).toContain('₹4,210')
    expect(html).toMatch(/data-testid="bought-NEWBIE"/)
    expect(html).not.toContain('data-testid="edit-row"') // nothing is in edit mode until Edit is tapped
    expect(html).not.toMatch(/NaN|undefined/)
  })

  const rowHtml = (over: Partial<WatchTrackerItem> = {}, initial?: Parameters<typeof EditableRow>[0]['initial']) =>
    renderToString(
      <QueryClientProvider client={new QueryClient()}>
        <EditableRow k={{ ...DATA.items[0]!, note: 'from Today', ...over }} horizon={15} onSaved={() => {}} onCancel={() => {}} initial={initial} />
      </QueryClientProvider>,
    )

  it('a row in edit mode shows boxes with the saved values, the note box and Save / Cancel', () => {
    const html = rowHtml()
    expect(html).toContain('data-testid="edit-row"')
    expect(html).toMatch(/type="date"[^>]*value="2026-10-28"/)
    expect(html).toContain('aria-label="Price you paid in Groww for KEI"')
    expect(html).toContain('value="4210"')
    expect(html).toContain('value="10"')
    expect(html).toContain('value="from Today"')
    expect(html).toContain('>Save<')
    expect(html).toContain('>Cancel<')
    // the server's numbers stay visible and read-only in the same row
    expect(html).toContain('+7.2%')
    expect(html).toContain('Reaching target')
    expect(html).not.toContain('data-testid="edit-row-error"')
    expect(html).not.toMatch(/NaN|undefined/)
  })

  it('a row with no saved price or shares starts with empty boxes, never the word null', () => {
    const html = rowHtml({ buy_price: null, quantity: null, note: null })
    expect(html).toContain('placeholder="₹ paid"')
    expect(html).toContain('placeholder="shares"')
    expect(html).not.toMatch(/NaN|undefined|null/)
  })

  it('a bad value shows its plain-English message right under the row', () => {
    const html = rowHtml({}, { price: 'abc', quantity: '-3' })
    expect(html).toContain('data-testid="edit-row-error"')
    expect(html).toContain('role="alert"')
    expect(html).not.toMatch(/NaN|undefined/)
    const future = rowHtml({}, { boughtOn: '2999-01-01' })
    expect(future).toContain('The buy date cannot be in the future.')
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
