// A bookmark or a refresh of a /trademind/... page must open that page. These tests use page.goto and
// page.reload on purpose: openPage() moves inside the app, so it cannot see a bug in the first render.
import type { Page } from '@playwright/test'

import status from './fixtures/status.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, test } from './support/test'

/** The account status arrives after who-you-are and the plan, as it does on a real fresh load. */
async function slowStatus(page: Page, answer: { status: number; body: object } = { status: 200, body: status }) {
  await page.route('**/api/v1/status', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700))
    await route.fulfill({ status: answer.status, json: answer.body })
  })
}

test.describe('fresh load of a TradeMind address', () => {
  for (const path of ['/trademind/records', '/trademind/control', '/trademind/stock/INFY', '/trademind/positions?from=bookmark#top']) {
    test(`owner: opening and refreshing ${path} stays there`, async ({ page }) => {
      await mockApi(page)
      await slowStatus(page)
      await page.goto(path)
      await expect(page.getByTestId('nav-today')).toBeVisible()
      await expect.poll(() => page.evaluate(() => location.pathname + location.search + location.hash)).toBe(path)

      await page.reload()
      await expect(page.getByTestId('nav-today')).toBeVisible()
      await expect.poll(() => page.evaluate(() => location.pathname + location.search + location.hash)).toBe(path)
    })
  }

  test('owner with the brain off still goes to the Dashboard', async ({ page }) => {
    await mockApi(page)
    await slowStatus(page, { status: 200, body: { ...status, brain_enabled: false } })
    await page.goto('/trademind/records')
    await expect(page).toHaveURL(/\/dashboard$/)
  })

  test('owner with an unreadable status is not left waiting', async ({ page }) => {
    await mockApi(page)
    await slowStatus(page, { status: 500, body: { detail: 'Internal server error' } })
    await page.goto('/trademind/records')
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15_000 })
  })

  test('member: refreshing a page stays there', async ({ page }) => {
    await mockApi(page, { role: 'member' })
    await page.goto('/trademind/records')
    await expect(page.getByTestId('nav-today')).toBeVisible()
    await page.reload()
    await expect(page.getByTestId('nav-today')).toBeVisible()
    await expect(page).toHaveURL(/\/trademind\/records$/)
  })

  test('member: an owner-only address still goes back to Today', async ({ page }) => {
    await mockApi(page, { role: 'member' })
    await page.goto('/trademind/control')
    await expect(page).toHaveURL(/\/trademind$/)
  })
})
