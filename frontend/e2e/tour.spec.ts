// ux5: the first-time tour. A new account sees it once by itself; Help in the top bar opens it again. Every other
// spec runs with the tour already marked seen (mockApi's tourSeen default), so it never covers their journeys.
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'

import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

const TITLES = [
  'What the words mean',
  'Paper money and real money',
  'What the brain does, and does not do',
  'The plan for every trade',
  'Where to look each day',
]

const tour = (page: Page) => page.getByRole('dialog', { name: /What the words mean|Paper money|What the brain|The plan|Where to look/ })

test.describe('first-time tour', () => {
  test('a new account sees it once by itself, and Help opens it again', async ({ page }) => {
    await mockApi(page, { tourSeen: false })
    await openPage(page, '/trademind')
    const dialog = tour(page)
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: TITLES[0] })).toBeFocused()
    await expect(dialog.getByText('Step 1 of 5')).toBeVisible()

    // Escape closes it, and it stays closed after a reload and on other pages.
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await page.reload()
    await expect(page.getByText('Market Mode')).toBeVisible()
    await openPage(page, '/trademind/positions')
    await expect(page.getByText('Position Details', { exact: true })).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    // Help reopens it, from the first screen.
    const help = page.getByRole('button', { name: 'Help' })
    await help.click()
    await expect(dialog.getByRole('heading', { name: TITLES[0] })).toBeVisible()
    await page.getByRole('button', { name: 'Close the tour' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(help).toBeFocused()
  })

  test('Next, Back and the arrow keys move through all five screens; Done closes it', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await expect(page.getByRole('dialog')).toHaveCount(0) // seen already: nothing opens by itself
    await page.getByRole('button', { name: 'Help' }).click()
    const dialog = tour(page)
    await expect(dialog.getByRole('button', { name: 'Back' })).toBeDisabled()
    for (let i = 1; i < TITLES.length; i++) {
      await dialog.getByRole('button', { name: 'Next' }).click()
      await expect(dialog.getByRole('heading', { name: TITLES[i] })).toBeVisible()
      await expect(dialog.getByText(`Step ${i + 1} of 5`)).toBeVisible()
    }
    await page.keyboard.press('ArrowLeft')
    await expect(dialog.getByRole('heading', { name: TITLES[3] })).toBeVisible()
    await page.keyboard.press('ArrowRight')
    await expect(dialog.getByRole('heading', { name: TITLES[4] })).toBeVisible()
    await dialog.getByRole('button', { name: 'Back' }).click()
    await expect(dialog.getByRole('heading', { name: TITLES[3] })).toBeVisible()
    await page.keyboard.press('ArrowRight')
    await dialog.getByRole('button', { name: 'Done' }).click()
    await expect(dialog).toHaveCount(0)
  })

  test('keyboard focus stays inside the tour', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await page.getByRole('button', { name: 'Help' }).click()
    const dialog = tour(page)
    await expect(dialog).toBeVisible()
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press('Tab')
      expect(await dialog.evaluate((d) => d.contains(document.activeElement)), `Tab ${i + 1} left the tour`).toBe(true)
    }
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Shift+Tab')
      expect(await dialog.evaluate((d) => d.contains(document.activeElement)), `Shift+Tab ${i + 1} left the tour`).toBe(true)
    }
  })

  test('a word on the first screen explains itself, and Escape closes only that box', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await page.getByRole('button', { name: 'Help' }).click()
    const dialog = tour(page)
    await dialog.getByRole('button', { name: /^TRADE/ }).click()
    await expect(dialog.getByText(/Worth buying now, at the suggested size/)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog.getByText(/Worth buying now, at the suggested size/)).toHaveCount(0)
    await expect(dialog).toBeVisible()
  })

  test('the owner with the real account is pointed to it; a page link closes the tour and opens the page', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await page.getByRole('button', { name: 'Help' }).click()
    const dialog = tour(page)
    await dialog.getByRole('button', { name: 'Next' }).click()
    await expect(dialog.getByText(/My Zerodha \(Real\)/)).toBeVisible()
    for (let i = 0; i < 3; i++) await dialog.getByRole('button', { name: 'Next' }).click()
    await expect(dialog.getByRole('link', { name: 'My Zerodha (Real)' })).toBeVisible()
    await dialog.getByRole('link', { name: 'Records' }).click()
    await expect(page).toHaveURL(/\/trademind\/records$/)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test('a non-owner sees it too, and is never pointed to a page they cannot open', async ({ page }) => {
    await mockApi(page, { role: 'member', tourSeen: false })
    await openPage(page, '/trademind')
    const dialog = tour(page)
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Next' }).click()
    await expect(dialog.getByText('This account shows paper money only.')).toBeVisible()
    await expect(dialog.getByText(/My Zerodha/)).toHaveCount(0)
    for (let i = 0; i < 3; i++) await dialog.getByRole('button', { name: 'Next' }).click()
    await expect(dialog.getByRole('heading', { name: TITLES[4] })).toBeVisible()
    await expect(dialog.getByText(/My Zerodha/)).toHaveCount(0)
    const links = await dialog.getByRole('link').evaluateAll((els) => els.map((a) => new URL((a as HTMLAnchorElement).href).pathname))
    expect(links.sort()).toEqual(
      ['/trademind', '/trademind/learn', '/trademind/opportunities', '/trademind/positions', '/trademind/records'].sort(),
    )
  })
})

/** Wait for one-off entrance animations to finish, so contrast is measured at full opacity. */
async function settle(page: Page) {
  await page.waitForFunction(() =>
    document.getAnimations().every((a) => {
      const iterations = a.effect?.getTiming().iterations ?? 1
      return iterations === Infinity || a.playState !== 'running'
    }),
  )
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`tour accessibility, ${scheme} colour scheme`, () => {
    test.use({ colorScheme: scheme })

    test('every screen of the tour has no serious or critical problems', async ({ page }) => {
      await mockApi(page, { tourSeen: false })
      await openPage(page, '/trademind')
      const dialog = tour(page)
      for (let i = 0; i < TITLES.length; i++) {
        await expect(dialog.getByRole('heading', { name: TITLES[i] })).toBeVisible()
        await settle(page)
        const results = await new AxeBuilder({ page })
          .include('[data-testid="tour"]')
          .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
          .analyze()
        const serious = results.violations
          .filter((v) => v.impact === 'serious' || v.impact === 'critical')
          .map((v) => ({ rule: v.id, help: v.help, where: v.nodes.slice(0, 5).map((n) => n.target.join(' ')) }))
        expect(serious, `accessibility problems on tour screen ${i + 1} (${scheme})`).toEqual([])
        if (i < TITLES.length - 1) await dialog.getByRole('button', { name: 'Next' }).click()
      }
    })
  })
}

test.describe('tour at phone width (390 x 844)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('fits the screen, every screen can be read, and the buttons can be tapped', async ({ page }) => {
    await mockApi(page, { tourSeen: false })
    await openPage(page, '/trademind')
    const dialog = tour(page)
    await expect(dialog).toBeVisible()
    for (let i = 0; i < TITLES.length; i++) {
      const box = (await dialog.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(390)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, 'page is wider than the phone screen').toBeLessThanOrEqual(0)
      const button = dialog.getByRole('button', { name: i < TITLES.length - 1 ? 'Next' : 'Done' })
      await button.scrollIntoViewIfNeeded()
      const b = (await button.boundingBox())!
      expect(b.height).toBeGreaterThanOrEqual(24)
      await button.tap()
    }
    await expect(dialog).toHaveCount(0)
  })
})
