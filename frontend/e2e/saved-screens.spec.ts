// #310 slice A journey: save the Discover filters under a name, change them, open the saved screen and see every
// control and the list come back (A1); a screen whose sector is gone says so and shows nothing else (A6); rename and
// delete. Against the fake backend (e2e/support/mockApi.ts) with an in-memory /me/screens; nothing reaches production.
import type { Page } from '@playwright/test'

import discoverRun from './fixtures/discover-run.json' with { type: 'json' }
import discoverSectors from './fixtures/discover-sectors.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, test } from './support/test'

const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })

type Screen = { id: number; name: string; spec: Record<string, unknown>; filters_version: number; created_at: null; updated_at: null }

async function setup(page: Page, seed: Screen[] = []) {
  await mockApi(page, { role: 'owner' })
  await page.addInitScript(() => localStorage.setItem('tm-look', 'new'))
  const screens = [...seed]
  let nextId = 100
  await page.route((u) => u.pathname === '/api/v1/brain/runs/latest', (r) => r.fulfill(json(discoverRun)))
  await page.route((u) => u.pathname === '/api/v1/market-data/sectors', (r) => r.fulfill(json(discoverSectors)))
  await page.route(
    (u) => u.pathname.startsWith('/api/v1/me/screens'),
    async (route) => {
      const req = route.request()
      const path = new URL(req.url()).pathname.replace('/api/v1/me/screens', '')
      const method = req.method()
      if (path === '' && method === 'GET') return route.fulfill(json({ screens, limit: 3 }))
      if (path === '' && method === 'POST') {
        const body = req.postDataJSON() as { name: string; spec: Record<string, unknown> }
        const made = { id: nextId++, name: body.name, spec: body.spec, filters_version: 1, created_at: null, updated_at: null } as Screen
        screens.push(made)
        return route.fulfill(json(made, 201))
      }
      const id = Number(path.split('/')[1])
      const row = screens.find((s) => s.id === id)
      if (path.endsWith('/digest'))
        return route.fulfill(
          json({
            comparable: false, note: 'There is no earlier nightly run to compare with yet.', current: null, previous: null,
            came_in: [], dropped_out: [], not_compared: [], footer: 'This is a ranking. It is not a chance of profit and not advice.',
          }),
        )
      if (!row) return route.fulfill(json({ detail: 'That saved screen was not found.' }, 404))
      if (method === 'PATCH') {
        const body = req.postDataJSON() as { name?: string; spec?: Record<string, unknown> }
        if (body.name) row.name = body.name
        if (body.spec) row.spec = body.spec
        return route.fulfill(json(row))
      }
      if (method === 'DELETE') {
        screens.splice(screens.indexOf(row), 1)
        return route.fulfill(json({ deleted: true, id }))
      }
      return route.fulfill(json(row))
    },
  )
}

async function openDiscover(page: Page) {
  await page.goto('/trademind/opportunities')
  await expect(page.locator('[data-page="discover-new"]')).toBeVisible()
}

const table = (page: Page) => page.getByTestId('discover-table')
const symbolsShown = (page: Page) => table(page).locator('tbody tr a.tmn-w2-stock b').allTextContents()
const pill = (page: Page, name: RegExp) => page.getByTestId('discover-filters').getByRole('button', { name })

test.describe('Saved screens (#310)', () => {
  test('save the filters, change them, open the saved screen: the same controls and the same list', async ({ page }) => {
    await setup(page)
    await openDiscover(page)
    await pill(page, /^WATCH/).click()
    const handSet = await symbolsShown(page)
    expect(handSet.length).toBeGreaterThan(0)

    await page.getByTestId('screen-save-new').click()
    await expect(page.getByTestId('screen-readback')).toContainText('WATCH')
    await page.getByTestId('screen-name').fill('Watch list')
    await page.getByTestId('screen-submit').click()
    await expect(page.getByTestId('screen-showing')).toContainText('WATCH')

    await pill(page, /^AVOID/).click() // change the filters
    expect(await symbolsShown(page)).not.toEqual(handSet)
    await page.getByTestId('saved-screens-menu').selectOption({ label: 'Watch list' })

    await expect(pill(page, /^WATCH/)).toHaveAttribute('aria-pressed', 'true')
    expect(await symbolsShown(page)).toEqual(handSet)
    await expect(page.getByTestId('changes-panel')).toContainText('Not enough scan history yet')
  })

  test('rename, then delete, only touches the saved screen', async ({ page }) => {
    const spec = { horizon: '15d', cap_tiers: [], patterns: [], word: 'ALL', sector: null, query: '', layout: 'table', watch_only: false }
    await setup(page, [{ id: 1, name: 'First', spec, filters_version: 1, created_at: null, updated_at: null }])
    await openDiscover(page)
    await page.getByTestId('saved-screens-menu').selectOption({ label: 'First' })
    await page.getByTestId('screen-rename').click()
    await page.getByTestId('screen-name').fill('Second')
    await page.getByTestId('screen-submit').click()
    await expect(page.getByTestId('saved-screens-menu')).toContainText('Second')
    await page.getByTestId('screen-delete').click()
    await expect(page.getByTestId('screen-confirm-delete')).toContainText('not touched')
    await page.getByTestId('screen-confirm-yes').click()
    await expect(page.getByTestId('saved-screens-menu')).not.toContainText('Second')
    await expect(page.getByTestId('screens-count')).toContainText('0 of 3')
  })

  test('a screen whose sector is gone says so and shows no other list', async ({ page }) => {
    const spec = { horizon: '15d', cap_tiers: [], patterns: [], word: 'ALL', sector: 'Sector that was removed', query: '', layout: 'table', watch_only: false }
    await setup(page, [{ id: 1, name: 'Old sector', spec, filters_version: 1, created_at: null, updated_at: null }])
    await openDiscover(page)
    await page.getByTestId('saved-screens-menu').selectOption({ label: 'Old sector' })
    await expect(page.getByTestId('screen-problem')).toContainText('no longer available')
    await expect(page.locator('[data-state="empty"]')).toContainText('No stocks match these filters.')
  })

  test('works at phone width without sideways scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 })
    await setup(page)
    await openDiscover(page)
    await expect(page.getByTestId('saved-screens')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
