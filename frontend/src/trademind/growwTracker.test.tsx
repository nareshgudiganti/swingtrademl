// Groww Tracker page: renders from the server's numbers (no recomputed status), shows dashes for missing numbers,
// and the menu item can be switched off per browser.
import { readFileSync } from 'node:fs'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../api/client'
import type { GrowwMatchItem, GrowwStatus, WatchTracker, WatchTrackerItem } from '../api/types'
import { LOOK_KEY } from './look'
import { TRACKER_TAB_KEY, readTrackerTab, writeTrackerTab } from './trackerTab'
import { Detail, EditableRow } from './pages/GrowwTracker'
import { GROWW_MATCH_KEY, acceptSuggestion, pickStock } from './GrowwMatchingPanel'
import { confirmEmptySync, refusalText, runRefresh } from './GrowwSyncStrip'
import { filterItems, fmtIstStamp, fmtNowPrice, isGrowwRow, needsActionCount, saleBody, symbolsIn } from './trackerRules'
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

function render(path: string, data: WatchTracker | undefined, extra?: (c: QueryClient) => void) {
  store.set(LOOK_KEY, 'new')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['plan'], { can_see_real_account: false, unrestricted: false, features: [] })
  if (data) client.setQueryData(['myWatchlistTracker'], data)
  extra?.(client)
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

  it('the detail panel has a close button, and starts open', () => {
    const html = render('/trademind/groww-tracker', DATA)
    expect(html).toContain('data-testid="tracker-detail-close"')
    expect(html).toContain('aria-label="Close this panel"')
    expect(html).not.toContain('gt-solo')
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

  describe('Groww sync', () => {
    // The test just above leaves a throwing localStorage behind; put the working one back.
    beforeEach(() => {
      vi.stubGlobal('localStorage', {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
        clear: () => store.clear(),
      })
    })
    const GROWW_FAILED: GrowwStatus = {
      configured: true,
      last_success_at: '2026-11-21T10:05:00Z', // 15:35 IST
      last_status: 'failed',
      last_attempt_at: '2026-11-21T11:00:00Z',
      last_sync_id: 7,
    }
    const withGroww = (groww?: GrowwStatus, items = DATA.items): WatchTracker => ({ ...DATA, items, ...(groww ? { groww } : {}) })

    it('shows last successful sync time when the latest sync failed', () => {
      const html = render('/trademind/groww-tracker', withGroww(GROWW_FAILED))
      expect(html).toContain('data-testid="groww-strip"')
      expect(html).toContain('Groww synced 21 Nov, 15:35 IST')
      expect(html).toContain('prices from 7 Nov close')
      expect(html).toContain('showing holdings from 21 Nov, 15:35 IST')
      expect(html).toContain('>Refresh<')
      expect(html).not.toMatch(/NaN|undefined|null/)
    })

    it('needs-matching panel lists unmatched rows and confirm posts instrument_id', async () => {
      const html = render('/trademind/groww-tracker', withGroww({ ...GROWW_FAILED, last_status: 'complete' }), (c) =>
        c.setQueryData(GROWW_MATCH_KEY, {
          items: [
            { isin: 'INE000A01011', trading_symbol: 'ACMEIND', quantity: 5, average_price: 120.5, match_state: 'needs_matching', suggested_symbol: null },
            { isin: 'INE000B01022', trading_symbol: 'BETACO', quantity: 2, average_price: 80, match_state: 'suggested', suggested_symbol: 'BETA' },
          ],
        }),
      )
      expect(html).toContain('data-testid="groww-matching"')
      expect(html).toContain('INE000A01011')
      expect(html).toContain('ACMEIND')
      expect(html).toContain('Suggested: BETA')
      expect(html).toContain('Confirm all suggestions')
    })

    it('choosing a search hit posts that hit\'s instrument id, not its symbol', async () => {
      const spy = vi.spyOn(api, 'growwMatch').mockResolvedValue({})
      const hit = { id: 42, tradingsymbol: 'ACMEIND', name: 'Acme Industries' }
      await pickStock('INE000A01011', hit)
      expect(spy).toHaveBeenCalledWith('INE000A01011', 42)
      spy.mockRestore()
    })

    it('Refresh: done, failed, already refreshing (neutral) and rate limited', async () => {
      const ok = await runRefresh(async () => ({ status: 'complete', holdings_count: 3, finished_at: 'x' }))
      expect(ok).toEqual({ kind: 'done', text: 'Done. 3 holdings from Groww.' })
      const failed = await runRefresh(async () => ({ status: 'failed', holdings_count: 0, finished_at: 'x' }))
      expect(failed.kind).toBe('failed')
      const busy = await runRefresh(async () => {
        throw new Error('already refreshing')
      })
      expect(busy.kind).toBe('busy')
      expect(busy.text).not.toMatch(/fail|did not/i)
      const limited = await runRefresh(async () => {
        throw new Error('Too many requests. Try again in a minute.')
      })
      expect(limited).toEqual({ kind: 'failed', text: 'Too many requests. Try again in a minute' })
    })

    it('Confirm on the empty banner posts the sync id, and does nothing without one', async () => {
      const spy = vi.spyOn(api, 'growwConfirmEmpty').mockResolvedValue({})
      await confirmEmptySync({ last_sync_id: 7 })
      expect(spy).toHaveBeenCalledWith(7)
      spy.mockClear()
      await confirmEmptySync({ last_sync_id: null })
      expect(spy).not.toHaveBeenCalled()
      spy.mockRestore()
    })

    it('the sale request carries the prefilled quantity, and none when the box is empty', () => {
      expect(saleBody('120.5', '2026-11-21', '4')).toEqual({ sell_price: 120.5, sold_on: '2026-11-21', quantity: 4 })
      expect(saleBody('120.5', '2026-11-21', '')).toEqual({ sell_price: 120.5, sold_on: '2026-11-21' })
    })

    it('quantity and price inputs are read-only on Groww rows', () => {
      const groww = rowHtml({ source: 'groww' })
      expect(groww).toContain('from Groww')
      expect(groww).not.toContain('aria-label="Price you paid in Groww for KEI"')
      expect(groww).not.toContain('aria-label="Shares of KEI"')
      expect(groww).toContain('₹4,210')
      expect(groww).toContain('aria-label="Bought on for KEI"')
      const manual = rowHtml({ source: 'manual' })
      expect(manual).toContain('aria-label="Shares of KEI"')
      expect(manual).not.toContain('from Groww')
    })

    it('confirm sale prefills the pending quantity', () => {
      const k = { ...DATA.items[0]!, source: 'groww' as const, pending_sale_qty: 4 }
      const html = renderToString(
        <QueryClientProvider client={new QueryClient()}>
          <Detail k={k} horizon={15} editing={false} onEditing={() => {}} onRemoved={() => {}} startSelling />
        </QueryClientProvider>,
      )
      expect(html).toMatch(/aria-label="Shares sold for KEI"[^>]*value="4"|value="4"[^>]*aria-label="Shares sold for KEI"/)
      // the row says why
      const rows = render('/trademind/groww-tracker', withGroww(GROWW_FAILED, [k]))
      expect(rows).toContain('Groww shows 4 fewer shares')
      expect(rows).toContain('Confirm sale')
    })

    it('not held rows are labelled and excluded from the held total', () => {
      const gone = item('GONE', 'ok', { source: 'groww', held_state: 'not_held', invested: 99900, profit_amount: 100 })
      const html = render('/trademind/groww-tracker', withGroww(GROWW_FAILED, [DATA.items[0]!, gone]))
      expect(html).toContain('Not held')
      const summary = html.slice(html.indexOf('data-testid="tracker-summary"'), html.indexOf('</section>', html.indexOf('data-testid="tracker-summary"')))
      expect(summary).toContain('₹42,100')
      expect(summary).not.toContain('₹1,42,000')
      expect(summary).not.toContain('₹99,900')
    })

    it('the Counts note counts held stocks only', () => {
      const gone = item('GONE', 'ok', { source: 'groww', held_state: 'not_held' })
      const noShares = DATA.items[2]! // held, but no shares or price
      const html = render('/trademind/groww-tracker', withGroww(GROWW_FAILED, [DATA.items[0]!, noShares, gone])).replace(/<!-- -->/g, '')
      expect(html).toContain('Counts 1 of 2 stocks.')
      expect(html).not.toContain('Counts 1 of 3 stocks.')
    })

    it('not held rows stay listed but raise no warnings or counts', () => {
      const gone = item('GONE', 'stop', { source: 'groww', held_state: 'not_held', return_pct: -9 })
      const items = [DATA.items[0]!, gone]
      expect(needsActionCount(items)).toBe(1) // only KEI (target)
      expect(symbolsIn(items, 'stop')).toEqual([])
      expect(filterItems(items, 'act').map((i) => i.symbol)).toEqual(['KEI'])
      expect(filterItems(items, 'all')).toHaveLength(2)
      const html = render('/trademind/groww-tracker', withGroww(GROWW_FAILED, items))
      expect(html).toContain('data-symbol="GONE"')
      expect(html).toContain('Not held')
      expect(html).toMatch(/Near stop-loss<\/h3><div class="gt-big num">0</)
      expect(html).not.toContain('Near stop-loss</span>')
    })

    it('non-owner sees no Groww strip', () => {
      const html = render('/trademind/groww-tracker', withGroww(undefined))
      expect(html).not.toContain('data-testid="groww-strip"')
      expect(html).not.toContain('data-testid="groww-matching"')
      expect(html).not.toContain('Refresh')
      expect(html).toContain('data-testid="tracker-table"')
    })

    it('an empty sync asks the owner to confirm', () => {
      const html = render('/trademind/groww-tracker', withGroww({ ...GROWW_FAILED, last_status: 'empty_unconfirmed' }))
      expect(html).toContain('Groww returned no holdings')
      expect(html).toContain('>Confirm<')
    })

    // ---- #388 finishing: the two contract mismatches, then the gaps found against spec section 6 ----

    it('a Refresh answer may carry no finish time (contract: finished_at is nullable)', async () => {
      const r = await runRefresh(async () => ({ status: 'complete', holdings_count: 1, finished_at: null }))
      expect(r).toEqual({ kind: 'done', text: 'Done. 1 holding from Groww.' })
    })

    it('a failed refresh has no holdings count and no finish time, and reads as a failure', async () => {
      const failed = await runRefresh(async () => ({ status: 'failed', holdings_count: null, finished_at: null }))
      expect(failed).toEqual({ kind: 'failed', text: 'Groww did not answer' })
      // a count that is missing on a refresh that did not fail never prints the word null
      const odd = await runRefresh(async () => ({ status: 'partial', holdings_count: null, finished_at: null }))
      expect(odd).toEqual({ kind: 'done', text: 'Done.' })
    })

    describe('a hand-entered row that a sync linked', () => {
      // The server keeps source "manual" on such a row; held_state says Groww has seen it.
      it.each(['held', 'not_held'] as const)('held_state %s: badge, read-only shares and price, sale may be partial', (held_state) => {
        const row = rowHtml({ source: 'manual', held_state })
        expect(row).toContain('from Groww')
        expect(row).not.toContain('aria-label="Price you paid in Groww for KEI"')
        expect(row).not.toContain('aria-label="Shares of KEI"')
        const k = { ...DATA.items[0]!, source: 'manual' as const, held_state }
        const sale = renderToString(
          <QueryClientProvider client={new QueryClient()}>
            <Detail k={k} horizon={15} editing={false} onEditing={() => {}} onRemoved={() => {}} startSelling />
          </QueryClientProvider>,
        )
        expect(sale).toContain('aria-label="Shares sold for KEI"')
        expect(isGrowwRow(k)).toBe(true)
      })
      it.each([undefined, 'unknown'] as const)('held_state %s: still a plain hand-entered row', (held_state) => {
        const over = held_state === undefined ? { source: 'manual' as const } : { source: 'manual' as const, held_state }
        const row = rowHtml(over)
        expect(row).not.toContain('from Groww')
        expect(row).toContain('aria-label="Shares of KEI"')
        expect(isGrowwRow({ ...DATA.items[0]!, ...over })).toBe(false)
      })
      it('the table row carries the badge too', () => {
        const linked = item('LINKED', 'ok', { source: 'manual', held_state: 'held' })
        const html = render('/trademind/groww-tracker', withGroww(GROWW_FAILED, [linked]))
        const row = html.slice(html.indexOf('data-symbol="LINKED"'))
        expect(row).toContain('from Groww')
      })
    })

    const SUGGESTED: GrowwMatchItem = {
      isin: 'INE000B01022',
      trading_symbol: 'BETACO',
      quantity: 2,
      average_price: 80,
      match_state: 'suggested',
      suggested_symbol: 'BETA',
      suggested_instrument_id: 22,
    }
    const UNMATCHED: GrowwMatchItem = {
      isin: 'INE000A01011',
      trading_symbol: 'ACMEIND',
      quantity: 5,
      average_price: 120.5,
      match_state: 'needs_matching',
      suggested_symbol: null,
      suggested_instrument_id: null,
    }

    it('a suggested row is accepted with its suggested instrument id, and a row without one posts nothing', async () => {
      const spy = vi.spyOn(api, 'growwMatch').mockResolvedValue({})
      await acceptSuggestion(SUGGESTED)
      expect(spy).toHaveBeenCalledWith('INE000B01022', 22)
      spy.mockClear()
      await acceptSuggestion(UNMATCHED)
      await acceptSuggestion({ ...SUGGESTED, suggested_instrument_id: null })
      expect(spy).not.toHaveBeenCalled()
      spy.mockRestore()
    })

    it('matching: "Use BETA" on a row with a suggestion, only the search box on a row without one', () => {
      const html = render('/trademind/groww-tracker', withGroww({ ...GROWW_FAILED, last_status: 'complete' }), (c) =>
        c.setQueryData(GROWW_MATCH_KEY, { items: [UNMATCHED, SUGGESTED] }),
      )
      expect(html.replace(/<!-- -->/g, '').match(/>Use BETA</g)).toHaveLength(1)
      expect(html).not.toContain('Use ACMEIND')
      expect(html).toContain('aria-label="Find the stock for INE000A01011"') // the search box is on both rows
      expect(html).toContain('aria-label="Find the stock for INE000B01022"')
    })

    it('matching that could not be loaded says so, instead of showing nothing', () => {
      const html = render('/trademind/groww-tracker', withGroww({ ...GROWW_FAILED, last_status: 'complete' }), (c) => {
        // a server render would otherwise show an errored query as "loading" (it retries on mount)
        c.setDefaultOptions({ queries: { retry: false, retryOnMount: false } })
        const query = c.getQueryCache().build(c, { queryKey: GROWW_MATCH_KEY, queryFn: api.growwMatching })
        query.setState({ ...query.state, status: 'error', error: new ApiError('Conflict', 409), fetchStatus: 'idle' })
      })
      expect(html).toContain('data-testid="groww-matching-error"')
      expect(html).toContain('Groww is busy or has no account to update right now')
    })

    // ---- the server may leave quantity, price and symbol empty (a partial sync) and counts rows with no ISIN ----

    it('a row with no quantity, price or symbol shows "unknown", never 0, and does not crash', () => {
      const holes: GrowwMatchItem = { ...UNMATCHED, isin: 'INE000C01033', trading_symbol: null, quantity: null, average_price: null }
      const html = render('/trademind/groww-tracker', withGroww({ ...GROWW_FAILED, last_status: 'partial' }), (c) =>
        c.setQueryData(GROWW_MATCH_KEY, { items: [holes], without_isin: 0 }),
      ).replace(/<!-- -->/g, '')
      expect(html).toContain('data-isin="INE000C01033"')
      expect(html).toContain('unknown shares at unknown price')
      expect(html).not.toMatch(/0 shares at|₹0|NaN|undefined|null/)
      // quantity and price known, symbol not: each hole is named on its own
      const partly = { ...UNMATCHED, trading_symbol: null }
      const out = render('/trademind/groww-tracker', withGroww(GROWW_FAILED), (c) =>
        c.setQueryData(GROWW_MATCH_KEY, { items: [partly], without_isin: 0 }),
      ).replace(/<!-- -->/g, '')
      expect(out).toContain('unknown')
      expect(out).toContain('5 shares at ₹120.5')
    })

    it('rows Groww gave no ISIN for are counted in one plain line, and are not listed', () => {
      const html = render('/trademind/groww-tracker', withGroww(GROWW_FAILED), (c) =>
        c.setQueryData(GROWW_MATCH_KEY, { items: [UNMATCHED], without_isin: 2 }),
      ).replace(/<!-- -->/g, '')
      expect(html).toContain('data-testid="groww-no-isin"')
      expect(html).toContain('2 Groww holdings cannot be matched because Groww gave no ISIN for them.')
      const one = render('/trademind/groww-tracker', withGroww(GROWW_FAILED), (c) =>
        c.setQueryData(GROWW_MATCH_KEY, { items: [], without_isin: 1 }),
      ).replace(/<!-- -->/g, '')
      expect(one).toContain('1 Groww holding cannot be matched because Groww gave no ISIN for it.')
      const none = render('/trademind/groww-tracker', withGroww(GROWW_FAILED), (c) =>
        c.setQueryData(GROWW_MATCH_KEY, { items: [UNMATCHED], without_isin: 0 }),
      )
      expect(none).not.toContain('data-testid="groww-no-isin"')
    })

    it('a row with a blank ISIN is counted like the others and never gets a request', async () => {
      const blank: GrowwMatchItem = { ...SUGGESTED, isin: '  ' }
      const html = render('/trademind/groww-tracker', withGroww(GROWW_FAILED), (c) =>
        c.setQueryData(GROWW_MATCH_KEY, { items: [blank, UNMATCHED], without_isin: 0 }),
      ).replace(/<!-- -->/g, '')
      expect(html).toContain('1 Groww holding cannot be matched because Groww gave no ISIN for it.')
      expect(html).not.toContain('Find the stock for  ')
      expect(html).not.toContain('Use BETA')
      const spy = vi.spyOn(api, 'growwMatch').mockResolvedValue({})
      await acceptSuggestion(blank)
      await pickStock('', { id: 22 })
      await pickStock('   ', { id: 22 })
      expect(spy).not.toHaveBeenCalled()
      spy.mockRestore()
    })

    it('a refresh that came back empty asks for the owner to confirm, and never says "Done. 0 holdings"', async () => {
      const r = await runRefresh(async () => ({ status: 'empty_unconfirmed', holdings_count: 0, finished_at: null }))
      expect(r.kind).toBe('confirm')
      expect(r.text).toBe('Groww returned no holdings. It needs your confirmation before anything changes.')
      expect(r.text).not.toMatch(/done|0 holdings/i)
    })

    it('every refusal reads as a plain sentence, whatever the server wrote', () => {
      const server: [number, string][] = [
        [403, "This is a private account. You don't have access."],
        [409, 'No owner account was found to update.'],
        [429, 'Groww was refreshed less than a minute ago. Try again soon.'],
        [503, 'Groww is not connected yet. Add the Groww keys on the server first.'],
      ]
      for (const [status, text] of server) expect(refusalText(new ApiError(text, status))).toBe(text.replace(/[.]$/, ''))
      // a bare HTTP phrase or a server error never reaches the owner
      expect(refusalText(new ApiError('Forbidden', 403))).toBe("This is a private account. You don't have access")
      expect(refusalText(new ApiError('Conflict', 409))).toBe('Groww is busy or has no account to update right now')
      expect(refusalText(new ApiError('Too Many Requests', 429))).toBe('Groww was refreshed less than a minute ago. Try again soon')
      expect(refusalText(new ApiError('Service Unavailable', 503))).toBe('Groww is not connected yet. Add the Groww keys on the server first')
      expect(refusalText(new ApiError('Internal Server Error', 500))).toBe('Groww did not answer')
      expect(refusalText(new TypeError('Failed to fetch'))).toBe('Groww did not answer')
    })

    it('a Refresh that is refused shows that plain sentence', async () => {
      const out = await runRefresh(async () => {
        throw new ApiError('Service Unavailable', 503)
      })
      expect(out).toEqual({ kind: 'failed', text: 'Groww is not connected yet. Add the Groww keys on the server first' })
    })

    it('a held stock with no price shows "no price yet", never a zero', () => {
      expect(fmtNowPrice(null)).toBe('no price yet')
      expect(fmtNowPrice(0)).toBe('no price yet')
      expect(fmtNowPrice(4512)).toBe('₹4,512')
      for (const last_price of [null, 0]) {
        const k = item('NOPRICE', 'ok', { source: 'groww', held_state: 'held', last_price, return_pct: null, today_pct: null })
        const html = render('/trademind/groww-tracker', withGroww(GROWW_FAILED, [k])).replace(/<!-- -->/g, '')
        expect(html).toContain('→ no price yet')
        expect(html).not.toContain('→ ₹0')
      }
    })

    it('a partial refresh keeps the last good holdings in view, with their time', () => {
      const html = render('/trademind/groww-tracker', withGroww({ ...GROWW_FAILED, last_status: 'partial' }))
      expect(html).toContain('data-testid="groww-fail"')
      expect(html).toContain('showing holdings from 21 Nov, 15:35 IST')
    })

    it('times are India time, and a late-evening UTC time lands on the next India day', () => {
      expect(fmtIstStamp('2026-11-21T10:05:00Z')).toBe('21 Nov, 15:35 IST')
      expect(fmtIstStamp('2026-11-21T20:00:00Z')).toBe('22 Nov, 01:30 IST')
      expect(fmtIstStamp(null)).toBeNull()
    })

    it('on a phone the strip and the matching rows wrap and only the table scrolls, inside itself', () => {
      const css = readFileSync(new URL('./newlook-tracker.css', import.meta.url), 'utf8')
      const rule = (selector: string) => {
        const at = css.indexOf(selector)
        return at < 0 ? '' : css.slice(at, css.indexOf('}', at))
      }
      expect(rule('.tm-new .gt-gsync-row')).toContain('flex-wrap: wrap')
      expect(rule('.tm-new .gt-gmatch-row')).toContain('flex-wrap: wrap')
      expect(rule('.tm-new .gt-gpick')).toContain('flex-wrap: wrap')
      expect(rule('.tm-new .gt-tbl')).toContain('overflow-x: auto')
    })
  })
})
