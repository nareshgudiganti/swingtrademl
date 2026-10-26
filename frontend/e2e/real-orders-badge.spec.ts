// tr5: the top bar says whether REAL Zerodha orders from My Holdings are switched on, on every page, for the real
// account's owner only. A failed answer shows nothing (never a wrong "OFF").
import realAccount from './fixtures/real-account.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

const PAGES = ['/trademind', '/trademind/opportunities', '/trademind/portfolio', '/trademind/risk']

test('OFF: a grey badge in the top bar', async ({ page }) => {
  await mockApi(page)
  await openPage(page, '/trademind')
  const badge = page.locator('.tm-topbar').getByTestId('real-orders-badge')
  await expect(badge).toHaveText(/Real orders: OFF/i)
  await expect(badge).toHaveAttribute('data-on', 'false')
})

test('ON: the top bar says so on every page', async ({ page }) => {
  await mockApi(page)
  // Registered after mockApi, so it answers this one path first.
  await page.route('**/api/v1/portfolio/real/orders-status', (r) =>
    r.fulfill({ json: { ...realAccount.ordersStatus, enabled: true } }),
  )
  for (const path of PAGES) {
    await openPage(page, path)
    const badge = page.locator('.tm-topbar').getByTestId('real-orders-badge')
    await expect(badge, path).toHaveText(/Real orders: ON/i)
    await expect(badge, path).toHaveAttribute('data-on', 'true')
  }
})

test('ON stays visible on a phone', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  const page = await context.newPage()
  await mockApi(page)
  await page.route('**/api/v1/portfolio/real/orders-status', (r) =>
    r.fulfill({ json: { ...realAccount.ordersStatus, enabled: true } }),
  )
  await page.goto('/trademind')
  await expect(page.getByTestId('real-orders-badge')).toBeVisible()
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(sideways, 'page scrolls sideways at 390px').toBe(false)
  await context.close()
})

test('a failed answer shows no badge', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/v1/portfolio/real/orders-status', (r) => r.fulfill({ status: 500, json: { detail: 'boom' } }))
  await openPage(page, '/trademind')
  await expect(page.getByTestId('brain-chip')).toBeVisible()
  await expect(page.getByTestId('real-orders-badge')).toHaveCount(0)
})

test('a member never sees it', async ({ page }) => {
  await mockApi(page, { role: 'member' })
  await openPage(page, '/trademind')
  await expect(page.getByTestId('brain-chip')).toBeVisible()
  await expect(page.getByTestId('real-orders-badge')).toHaveCount(0)
})
