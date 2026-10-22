// oa8: the top-bar alerts bell and trading-stage chip. The bell lists what /brain/alerts (the brain_alerts table)
// returns, the chip says what /brain/stage says, "seen" lives in this browser only (no write is ever sent), and an
// account the server refuses sees neither.
import brainAlerts from './fixtures/brain-alerts.json' with { type: 'json' }
import brainStage from './fixtures/brain-stage.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

const SEEN_KEY = 'tm.alerts.seen.v1' // same key as src/trademind/bellRules.ts

test.describe('alerts bell (owner)', () => {
  test('lists the recent alerts, newest first, and the chip equals /brain/stage', async ({ page }) => {
    const writes: string[] = []
    page.on('request', (r) => {
      if (r.url().includes('/api/v1/') && r.method() !== 'GET') writes.push(`${r.method()} ${r.url()}`)
    })
    await mockApi(page)
    await openPage(page, '/trademind')

    const chip = page.getByTestId('stage-chip')
    await expect(chip).toHaveAttribute('data-stage', brainStage.stage)
    await expect(chip).toContainText('Practice')

    const bell = page.getByRole('button', { name: 'Alerts, 2 new' })
    await expect(bell).toBeVisible()
    await bell.click()
    const panel = page.getByRole('region', { name: 'Recent alerts' })
    await expect(panel).toBeVisible()
    const items = panel.getByRole('listitem')
    await expect(items).toHaveCount(brainAlerts.length)
    await expect(items.first()).toContainText(brainAlerts[0]!.text)
    await expect(items.nth(1)).toContainText(brainAlerts[1]!.text)

    // Seen is remembered in this browser only.
    expect(await page.evaluate((k) => localStorage.getItem(k), SEEN_KEY)).toBe(String(brainAlerts[0]!.id))
    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    await expect(page.getByRole('button', { name: 'Alerts', exact: true })).toBeVisible()
    expect(writes, 'the bell must never write to the server').toEqual([])
  })

  test('the panel fits a 390px phone screen without sideways scrolling', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
    const page = await context.newPage()
    await mockApi(page)
    // Not openPage: on a phone the section row is the bottom bar, so the top row's Today link is hidden.
    await page.goto('/trademind')
    await page.getByTestId('alerts-bell').tap()
    const panel = page.getByTestId('alerts-panel')
    await expect(panel).toBeVisible()
    // The chip is hidden on a phone; the stage is shown at the top of the list instead.
    await expect(page.getByTestId('bell-stage')).toHaveText('Trading stage: Practice')
    const box = (await panel.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(390)
    const sideways = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
    expect(sideways, 'page scrolls sideways at 390px').toBe(false)
    const bellBox = (await page.getByTestId('alerts-bell').boundingBox())!
    expect(bellBox.width).toBeGreaterThanOrEqual(24)
    expect(bellBox.height).toBeGreaterThanOrEqual(24)
    await context.close()
  })

  test('when the server refuses, the top bar shows neither bell nor chip, and no error', async ({ page }) => {
    await mockApi(page)
    // Registered after mockApi, so these answers win.
    await page.route(
      (url) => url.pathname === '/api/v1/brain/alerts' || url.pathname === '/api/v1/brain/stage',
      (route) => route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'Owner only.' }) }),
    )
    await openPage(page, '/trademind')
    await expect(page.getByText('Market Mode').first()).toBeVisible()
    await expect(page.getByTestId('alerts-bell')).toHaveCount(0)
    await expect(page.getByTestId('stage-chip')).toHaveCount(0)
    await expect(page.locator('.tm-topbar')).not.toContainText('Owner only')
  })
})

test('a member sees no bell and no stage chip', async ({ page }) => {
  await mockApi(page, { role: 'member' })
  await openPage(page, '/trademind')
  await expect(page.getByText('Market Mode').first()).toBeVisible()
  await expect(page.getByTestId('alerts-bell')).toHaveCount(0)
  await expect(page.getByTestId('stage-chip')).toHaveCount(0)
})
