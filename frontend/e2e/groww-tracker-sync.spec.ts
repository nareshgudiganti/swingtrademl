// #388 Groww Tracker sync, as a person uses it, on mocked API data only (no backend, no Groww, nothing real).
// The shared fake backend (support/mockApi.ts) refuses every write, so this file adds its own answers for the
// tracker and /groww routes AFTER mockApi (a later page.route wins) and records every call it receives.
import type { Page, Route } from '@playwright/test'

import { mockApi, type Role } from './support/mockApi'
import { expect, openPage, test } from './support/test'

const PATH = '/trademind/groww-tracker'
const ISIN_ECHO = 'INE0EEE01015'

type Call = { method: string; path: string; body: unknown }

/** One invented tracker row; every number is made up. */
function row(symbol: string, over: Record<string, unknown> = {}) {
  return {
    symbol,
    name: `${symbol} Ltd`,
    added_at: '2026-10-28T05:00:00Z',
    note: null,
    buy_price: 300,
    bought_on: '2026-10-28',
    quantity: 7,
    invested: 2100,
    profit_amount: 120,
    entry_price: 300,
    entry_source: 'your_price',
    last_price: 317,
    return_pct: 5.6,
    today_pct: 0.4,
    days_done: 6,
    day_number: 7,
    score_today: 78,
    score_prev: 77,
    score_delta: 1,
    score_first: 72,
    scores: [72, 75, 77, 78].map((score, i) => ({ date: `2026-11-${17 + i}`, score })),
    closes: [300, 305, 311, 317].map((close, i) => ({ date: `2026-11-${17 + i}`, close })),
    state: 'ok',
    source: 'manual',
    held_state: 'unknown',
    groww_synced_at: null,
    pending_sale_qty: null,
    ...over,
  }
}

const OWNER_ITEMS = () => [
  row('GWROW', { source: 'groww', held_state: 'held', groww_synced_at: '2026-11-20T10:05:00Z' }),
  // A hand-entered row the first sync linked: Groww-owned numbers, and Groww now shows 6 fewer shares.
  row('ALPHA', { held_state: 'held', quantity: 9, pending_sale_qty: 6, groww_synced_at: '2026-11-20T10:05:00Z' }),
  row('GONE', { held_state: 'not_held', quantity: 0, groww_synced_at: '2026-11-20T10:05:00Z' }),
  row('DELTA', { quantity: 2, buy_price: 70, entry_price: 70 }),
]

const STATUS_OK = {
  configured: true,
  last_success_at: '2026-11-20T10:05:00Z',
  last_status: 'complete',
  last_attempt_at: '2026-11-20T10:05:00Z',
  last_sync_id: 11,
}

const MATCHING = () => [
  { isin: 'INE0AAA01011', trading_symbol: 'ALPHAX-EQ', quantity: 10, average_price: 100.5, match_state: 'suggested', suggested_symbol: 'ALPHA', suggested_instrument_id: 4 },
  { isin: ISIN_ECHO, trading_symbol: 'ECHOX-EQ', quantity: 3, average_price: 400, match_state: 'needs_matching', suggested_symbol: null, suggested_instrument_id: null },
]

type World = {
  calls: Call[]
  status: Record<string, unknown> | null
  items: Record<string, unknown>[]
  matching: Record<string, unknown>[]
  refreshStatus: string
  refreshFails: boolean
}

/** Layer the Groww answers over the shared fake backend. `status: null` means the server omits `groww`. */
async function growwWorld(page: Page, role: Role, over: Partial<World> = {}): Promise<World> {
  const world: World = { calls: [], status: STATUS_OK, items: OWNER_ITEMS(), matching: MATCHING(), refreshStatus: 'complete', refreshFails: false, ...over }
  await mockApi(page, { role })
  await page.route(
    (url) => url.pathname.startsWith('/api/v1/'),
    async (route: Route) => {
      const req = route.request()
      const path = new URL(req.url()).pathname.slice('/api/v1'.length)
      const method = req.method()
      let body: unknown = null
      try {
        body = req.postDataJSON()
      } catch {
        /* no JSON body */
      }
      const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
      const mine = path.startsWith('/groww') || path.startsWith('/me/watchlist') || path.startsWith('/instruments')
      if (!mine) return route.fallback()
      if (path.startsWith('/groww') || (method !== 'GET' && path.startsWith('/me/watchlist'))) world.calls.push({ method, path, body })

      if (method === 'GET' && path === '/me/watchlist/tracker') {
        return json({ as_of: '2026-11-20', horizon_days: 15, items: world.items, ...(world.status ? { groww: world.status } : {}) })
      }
      if (method === 'GET' && path === '/me/watchlist/sold') return json({ items: [] })
      if (method === 'GET' && path === '/instruments') return json([{ id: 5, instrument_token: 5, tradingsymbol: 'ECHO', name: 'Echo Ltd', exchange: 'NSE', instrument_type: 'EQ', lot_size: 1, tick_size: 0.05, is_watchlisted: false, is_active: true }])
      if (method === 'GET' && path === '/groww/matching') return json({ items: world.matching })
      if (method === 'POST' && path === '/groww/sync') {
        if (world.refreshFails) return json({ detail: 'Groww was refreshed less than a minute ago. Try again soon.' }, 429)
        world.status = { ...STATUS_OK, last_status: world.refreshStatus }
        return json({ status: world.refreshStatus, holdings_count: 3, finished_at: '2026-11-20T10:06:00Z' })
      }
      if (method === 'POST' && path === '/groww/matching/confirm-all') {
        world.matching = world.matching.filter((m) => m.match_state !== 'suggested')
        return json({ confirmed: 1 })
      }
      if (method === 'POST' && path.startsWith('/groww/matching/')) {
        world.matching = world.matching.filter((m) => m.isin !== path.split('/').pop())
        return json({ isin: path.split('/').pop(), instrument_id: (body as { instrument_id?: number } | null)?.instrument_id })
      }
      if (method === 'POST' && /^\/groww\/syncs\/\d+\/confirm-empty$/.test(path)) {
        world.status = { ...STATUS_OK }
        return json({ sync_id: Number(path.split('/')[3]), status: 'complete' })
      }
      if (method === 'POST' && /^\/me\/watchlist\/[A-Z]+\/sold$/.test(path)) {
        world.items = world.items.map((i) => (i.symbol === path.split('/')[3] ? { ...i, pending_sale_qty: null } : i))
        return json({ symbol: path.split('/')[3], sold_on: '2026-11-20', result: 'win' })
      }
      if (method === 'PATCH' && path.startsWith('/me/watchlist/')) {
        // The real server refuses quantity or price on a linked row.
        return json({ detail: 'This comes from Groww and updates on every sync.' }, 409)
      }
      return json({ detail: 'Not found (not in the Groww browser-test answers).' }, 404)
    },
  )
  return world
}

const sold = (w: World) => w.calls.filter((c) => /\/sold$/.test(c.path))

test.describe('Groww Tracker sync: the owner', () => {
  test('first screen: synced time, matching panel, refresh, not-held row, confirm a sale', async ({ page }) => {
    const world = await growwWorld(page, 'owner')
    await openPage(page, PATH)

    // The strip says when Groww last synced, in IST, with the price date.
    const strip = page.getByTestId('groww-strip')
    await expect(strip).toContainText('Groww synced 20 Nov, 15:35 IST')
    await expect(strip).toContainText('prices from 20 Nov close')
    await expect(page.getByTestId('groww-fail')).toHaveCount(0)

    // Needs matching: one suggestion, one unknown. "Confirm all" clears the suggestion; the unknown stays.
    const panel = page.getByTestId('groww-matching')
    await expect(panel).toBeVisible()
    await expect(panel.locator('[data-isin]')).toHaveCount(2)
    await expect(panel).toContainText('Suggested: ALPHA')
    await panel.getByRole('button', { name: 'Confirm all suggestions' }).click()
    await expect(panel.locator('[data-isin]')).toHaveCount(1)
    expect(world.calls.some((c) => c.method === 'POST' && c.path === '/groww/matching/confirm-all')).toBe(true)

    // Pick the stock for the unknown holding by search: the request carries that stock's id.
    await panel.getByLabel(`Find the stock for ${ISIN_ECHO}`).fill('ECH')
    await panel.getByRole('button', { name: /ECHO/ }).click()
    await expect(page.getByTestId('groww-matching')).toHaveCount(0)
    const picked = world.calls.find((c) => c.path === `/groww/matching/${ISIN_ECHO}`)
    expect(picked?.body).toEqual({ instrument_id: 5 })

    // Refresh says what came back.
    await page.getByTestId('groww-refresh').click()
    await expect(strip).toContainText('Done. 3 holdings from Groww.')
    expect(world.calls.filter((c) => c.path === '/groww/sync')).toHaveLength(1)

    // A stock Groww no longer lists is marked, and the linked row shows the missing shares with Confirm sale.
    await expect(page.getByText('Not held').first()).toBeVisible()
    await expect(page.getByText('Groww shows 6 fewer shares')).toBeVisible()
    await page.getByTestId('confirm-sale-ALPHA').click()
    const detail = page.getByTestId('tracker-detail')
    await expect(detail).toHaveAttribute('data-symbol', 'ALPHA')
    await expect(detail.getByLabel('Shares sold for ALPHA')).toHaveValue('6')
    await detail.getByLabel('Sell price for ALPHA').fill('120')
    await detail.getByRole('button', { name: 'Save sale' }).click()
    await expect.poll(() => sold(world).length).toBe(1)
    expect(sold(world)[0]!.body).toMatchObject({ sell_price: 120, quantity: 6 })
    await expect(page.getByText('Groww shows 6 fewer shares')).toHaveCount(0)
  })

  test('a refresh the server turns down shows its plain reason, not a blank', async ({ page }) => {
    await growwWorld(page, 'owner', { refreshFails: true })
    await openPage(page, PATH)
    await page.getByTestId('groww-refresh').click()
    await expect(page.getByTestId('groww-fail')).toContainText('Groww was refreshed less than a minute ago')
  })

  test('stale state: a failed or partial last refresh keeps the last good holdings visible and says when', async ({ page }) => {
    await growwWorld(page, 'owner', { status: { ...STATUS_OK, last_status: 'partial', last_attempt_at: '2026-11-21T10:05:00Z' } })
    await openPage(page, PATH)
    const fail = page.getByTestId('groww-fail')
    await expect(fail).toContainText('The last refresh did not finish')
    await expect(fail).toContainText('showing holdings from 20 Nov, 15:35 IST')
    await expect(page.getByTestId('tracker-table')).toContainText('GWROW')
  })

  test('never synced: says so, and nothing says holdings are stale', async ({ page }) => {
    await growwWorld(page, 'owner', { status: { ...STATUS_OK, last_success_at: null, last_status: null, last_attempt_at: null, last_sync_id: null }, matching: [] })
    await openPage(page, PATH)
    await expect(page.getByTestId('groww-strip')).toContainText('Groww has not synced yet.')
    await expect(page.getByTestId('groww-fail')).toHaveCount(0)
  })

  test('not set up on the server: no Refresh button and no matching panel', async ({ page }) => {
    await growwWorld(page, 'owner', { status: { ...STATUS_OK, configured: false, last_success_at: null, last_status: null, last_attempt_at: null, last_sync_id: null } })
    await openPage(page, PATH)
    await expect(page.getByTestId('groww-strip')).toContainText('Groww sync is not set up yet.')
    await expect(page.getByTestId('groww-refresh')).toHaveCount(0)
    await expect(page.getByTestId('groww-matching')).toHaveCount(0)
  })

  test('empty state: an empty Groww answer waits for the owner to confirm', async ({ page }) => {
    const world = await growwWorld(page, 'owner', { status: { ...STATUS_OK, last_status: 'empty_unconfirmed', last_sync_id: 12 }, matching: [] })
    await openPage(page, PATH)
    const banner = page.getByTestId('groww-empty-banner')
    await expect(banner).toContainText('Groww returned no holdings')
    await banner.getByRole('button', { name: 'Confirm' }).click()
    await expect(page.getByTestId('groww-empty-banner')).toHaveCount(0)
    expect(world.calls.some((c) => c.method === 'POST' && c.path === '/groww/syncs/12/confirm-empty')).toBe(true)
  })

  test('loading state: the page shows a notice, not a crash, while the tracker is slow', async ({ page }) => {
    await growwWorld(page, 'owner')
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => (release = resolve))
    await page.route('**/api/v1/me/watchlist/tracker', async (route) => {
      await gate
      await route.fallback()
    })
    await openPage(page, PATH)
    await expect(page.getByRole('heading', { name: 'Groww Tracker' })).toBeVisible()
    await expect(page.getByTestId('groww-strip')).toHaveCount(0)
    release()
    await expect(page.getByTestId('groww-strip')).toBeVisible()
  })

  test('error state: a tracker that fails to load shows an error, not an empty list', async ({ page }) => {
    await growwWorld(page, 'owner')
    await page.route('**/api/v1/me/watchlist/tracker', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Server error' }) }),
    )
    await openPage(page, PATH)
    await expect(page.getByRole('heading', { name: 'Groww Tracker' })).toBeVisible()
    await expect(page.getByTestId('groww-strip')).toHaveCount(0)
    await expect(page.getByTestId('tracker-table')).toHaveCount(0)
  })

  // A hand-entered row that the first sync linked has source 'manual'; held_state tells the screen it is Groww's now.
  test('a hand-entered row that Groww now owns shows no editable shares or price', async ({ page }) => {
    await growwWorld(page, 'owner')
    await openPage(page, PATH)
    await page.getByTestId('edit-ALPHA').click()
    await expect(page.getByLabel('Shares of ALPHA')).toHaveCount(0)
    await expect(page.getByLabel('Price you paid in Groww for ALPHA')).toHaveCount(0)
  })
})

for (const role of ['member', 'tester'] as const) {
  test.describe(`Groww Tracker sync: a ${role}`, () => {
    test('sees no Groww strip, no matching panel and never calls a /groww route', async ({ page }) => {
      const world = await growwWorld(page, role, {
        status: null,
        items: [row('DELTA', { quantity: 2, buy_price: 70, entry_price: 70 })],
        matching: [],
      })
      await openPage(page, PATH)
      await expect(page.getByRole('heading', { name: 'Groww Tracker' })).toBeVisible()
      await expect(page.getByTestId('tracker-table')).toContainText('DELTA')
      await expect(page.getByTestId('groww-strip')).toHaveCount(0)
      await expect(page.getByTestId('groww-matching')).toHaveCount(0)
      await expect(page.getByTestId('groww-refresh')).toHaveCount(0)
      await expect(page.getByText('from Groww')).toHaveCount(0)
      expect(world.calls.filter((c) => c.path.startsWith('/groww'))).toEqual([])
    })
  })
}

test.describe('Groww Tracker sync: a second owner (the server sends no groww key)', () => {
  test('sees no strip, no matching panel and never calls a /groww route', async ({ page }) => {
    const world = await growwWorld(page, 'owner', { status: null, items: [row('DELTA')], matching: [] })
    await openPage(page, PATH)
    await expect(page.getByTestId('tracker-table')).toContainText('DELTA')
    await expect(page.getByTestId('groww-strip')).toHaveCount(0)
    await expect(page.getByTestId('groww-matching')).toHaveCount(0)
    await expect(page.getByTestId('groww-refresh')).toHaveCount(0)
    expect(world.calls.filter((c) => c.path.startsWith('/groww'))).toEqual([])
  })
})

test.describe('Groww Tracker sync: a 360 px phone', () => {
  test.use({ viewport: { width: 360, height: 740 } })

  test('the owner can read the strip, matching panel and confirm a sale without sideways page scrolling', async ({ page }) => {
    const world = await growwWorld(page, 'owner')
    await openPage(page, PATH)
    const strip = page.getByTestId('groww-strip')
    await expect(strip).toBeVisible()
    await expect(page.getByTestId('groww-matching')).toBeVisible()

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, 'the page itself must not scroll sideways').toBeLessThanOrEqual(1)

    const refresh = page.getByTestId('groww-refresh')
    const box = await refresh.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(360)
    expect(box!.height).toBeGreaterThanOrEqual(28)

    await page.getByTestId('confirm-sale-ALPHA').click()
    const detail = page.getByTestId('tracker-detail')
    await expect(detail.getByLabel('Shares sold for ALPHA')).toHaveValue('6')
    const input = await detail.getByLabel('Sell price for ALPHA').boundingBox()
    expect(input!.x).toBeGreaterThanOrEqual(0)
    expect(input!.x + input!.width).toBeLessThanOrEqual(360)
    await detail.getByLabel('Sell price for ALPHA').fill('120')
    await detail.getByRole('button', { name: 'Save sale' }).click()
    await expect.poll(() => sold(world).length).toBe(1)
  })

  test('a non-owner on a phone sees the plain tracker with no Groww controls', async ({ page }) => {
    await growwWorld(page, 'member', { status: null, items: [row('DELTA')], matching: [] })
    await openPage(page, PATH)
    await expect(page.getByTestId('tracker-table')).toContainText('DELTA')
    await expect(page.getByTestId('groww-strip')).toHaveCount(0)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
