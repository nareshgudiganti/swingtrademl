// oa5: the one Today page (Home + Swing Picks), per role, in a real browser against the fake backend.
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

test.describe('Today (oa5)', () => {
  test('owner: status strip with safety, needs you, top cards with the horizon selector, and the pick list', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')

    const strip = page.getByTestId('status-strip')
    await expect(strip.getByText('Market Mode')).toBeVisible()
    await expect(strip.getByText('The market is steady. New trades are allowed within the usual limits.')).toBeVisible()
    await expect(strip.locator('[data-feature="kill-switch"]')).toContainText('Allowed')
    await expect(strip.locator('[data-feature="drawdown"]')).toContainText('below its peak')
    await expect(strip.locator('[data-feature="stage"]')).toContainText('Practice')

    const needs = page.getByTestId('needs-you')
    await expect(needs.getByText('Holdings Needing Attention', { exact: true })).toBeVisible()
    await expect(needs.getByText('Price slipped below its 10-day average.', { exact: true })).toBeVisible()
    await expect(needs.getByText('Waiting for your decision', { exact: true })).toBeVisible()
    await expect(needs.getByText('No idea is waiting for your OK.')).toBeVisible()

    // Top ideas: the one card, at most five.
    const cards = page.locator('[data-testid="top-ideas"] [data-card="idea"]')
    await expect(cards.first()).toBeVisible()
    expect(await cards.count()).toBeLessThanOrEqual(5)
    await expect(page.locator('#picks')).toContainText('All of today')
    await expect(page.locator('[data-feature="pick-table"]')).toContainText('INFY')

    // A window with no strategy shows that, never the 15-day cards under its name.
    await page.getByRole('tablist', { name: 'Trading horizon', exact: true }).getByRole('tab', { name: /30 Days/ }).click()
    await expect(page.locator('[data-feature="top-ideas"]')).toContainText('No supported trading strategy for 30 Days')
    await expect(cards).toHaveCount(0)
    await page.getByRole('tablist', { name: 'Trading horizon', exact: true }).getByRole('tab', { name: /15 Days/ }).click()
    await expect(cards.first()).toBeVisible()
  })

  test('Today is one page (no Swing Picks tab), and /trademind/dashboard still opens Today at the pick list', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await expect(page.getByTestId('subnav')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Swing Picks', exact: true })).toHaveCount(0)
    await openPage(page, '/trademind/dashboard')
    await expect(page).toHaveURL(/\/trademind\/dashboard$/)
    await expect(page.getByTestId('subnav')).toHaveCount(0)
    await expect(page.getByTestId('status-strip')).toHaveCount(1)
    await expect(page.locator('#picks')).toBeInViewport()
  })

  test('tester: no safety switches or approvals on Today; the strategy signals list is in Discover', async ({ page }) => {
    await mockApi(page, { role: 'tester' })
    await openPage(page, '/trademind')
    await expect(page.getByTestId('status-strip').getByText('Market Mode')).toBeVisible()
    await expect(page.locator('[data-feature="kill-switch"]')).toHaveCount(0)
    await expect(page.locator('[data-feature="approvals-waiting"]')).toHaveCount(0)
    await expect(page.getByTestId('needs-you').getByText('Holdings Needing Attention', { exact: true })).toBeVisible()
    await expect(page.locator('[data-testid="top-ideas"] [data-card="idea"]').first()).toBeVisible()

    await openPage(page, '/trademind/opportunities')
    await page.getByText('Show the signals').click()
    const table = page.getByTestId('strategy-signals')
    await expect(table).toContainText('INFY')
    await expect(table).toContainText('Experimental, unproven')
    await expect(table).not.toContainText('%')
  })

  test('member: no safety, no approvals, no strategy signals; the cards are there', async ({ page }) => {
    await mockApi(page, { role: 'member' })
    await openPage(page, '/trademind')
    await expect(page.getByTestId('status-strip').getByText('Market Mode')).toBeVisible()
    for (const f of ['kill-switch', 'drawdown', 'stage', 'approvals-waiting', 'proposals-waiting']) {
      await expect(page.locator(`[data-feature="${f}"]`)).toHaveCount(0)
    }
    await expect(page.locator('[data-testid="top-ideas"] [data-card="idea"]').first()).toBeVisible()
    await expect(page.locator('.tm-page')).not.toContainText(/My Zerodha|real money/i)

    await openPage(page, '/trademind/opportunities')
    await expect(page.locator('[data-card="idea"]').first()).toBeVisible()
    await expect(page.locator('[data-feature="classic-strategy-signals"]')).toHaveCount(0)
  })
})

test.describe('Today at phone width (390 x 844)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  for (const role of ['owner', 'tester', 'member'] as const) {
    for (const path of ['/trademind', '/trademind/dashboard']) {
      test(`${role}: no sideways scrolling on ${path}`, async ({ page }) => {
        await mockApi(page, { role })
        await openPage(page, path)
        await expect(page.getByTestId('status-strip')).toBeVisible()
        await expect(page.locator('[data-feature="pick-table"]')).toBeAttached()
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
        expect(overflow, 'page is wider than the phone screen').toBeLessThanOrEqual(0)
      })
    }
  }
})
