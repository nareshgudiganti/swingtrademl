// The shared test setup: a page whose uncaught JavaScript errors fail the test (a blank or crashed screen must
// never pass just because a heading happened to render first).
import { expect, test as base, type Page } from '@playwright/test'

export const test = base.extend<{ pageErrors: string[] }>({
  pageErrors: [
    async ({ page }, use) => {
      const errors: string[] = []
      page.on('pageerror', (err) => errors.push(err.message))
      await use(errors)
      expect(errors, 'uncaught errors in the page').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }

/**
 * Open a TradeMind page the way a person does: load the app, wait for the menu, then move inside the app.
 *
 * This covers clicking around inside the app. It cannot catch a bug in a fresh load (bookmark, refresh) of a
 * page: for that use page.goto(path), as deep-link.spec.ts does.
 */
export async function openPage(page: Page, path: string) {
  await page.goto('/trademind')
  await expect(page.getByTestId('nav-today')).toBeVisible()
  if (path !== '/trademind') {
    await page.evaluate((to) => {
      window.history.pushState({}, '', to)
      window.dispatchEvent(new PopStateEvent('popstate'))
    }, path)
  }
}

/** The pages the journeys visit, with the text that proves each one actually drew its content. */
export const PAGES = {
  today: { path: '/trademind', ready: 'Market Mode' },
  stock: { path: '/trademind/stock/INFY', ready: 'INFY' },
  portfolioBot: { path: '/trademind/positions', ready: 'TCS' },
  portfolioTesting: { path: '/trademind/testing', ready: 'Testing' },
  portfolioReal: { path: '/trademind/holdings', ready: 'Zerodha' },
  portfolioOverview: { path: '/trademind/portfolio', ready: 'TCS' },
  admin: { path: '/trademind/control', ready: 'Control' },
} as const
