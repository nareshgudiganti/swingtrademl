// tr3 (owner 2026-10-25): idea cards have no Buy button; practice buys live on Portfolio -> Manual test,
// shown to the owner and testers only. Fake backend only.
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

test.describe('Manual test page (tr3)', () => {
  test('Discover idea cards, including AVOID, have no Buy button', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind/opportunities')
    await expect(page.locator('[data-card="idea"]').first()).toBeVisible()
    await expect(page.getByRole('button', { name: /^(Buy|Paper buy)$/ })).toHaveCount(0)
  })

  for (const role of ['owner', 'tester'] as const) {
    test(`${role}: picks a stock and quantity and makes a practice buy`, async ({ page }) => {
      await mockApi(page, { role })
      await openPage(page, '/trademind/positions')
      await page.getByRole('link', { name: /Manual test/ }).first().click()
      await expect(page.getByTestId('manual-test-line')).toHaveText('Practice money only. This is your own test, not a brain pick.')
      await page.getByRole('combobox', { name: 'Stock' }).fill('INFY')
      await page.getByLabel('Quantity').fill('3')
      await page.getByRole('button', { name: 'Paper buy' }).click()
      await expect(page.getByText(/Practice buy placed: 3 × INFY/)).toBeVisible()
    })
  }

  test('member: no Manual test tab, and the address sends them back to Today', async ({ page }) => {
    await mockApi(page, { role: 'member' })
    await openPage(page, '/trademind/positions')
    await expect(page.getByRole('link', { name: /Manual test/ })).toHaveCount(0)
    await openPage(page, '/trademind/manual-test')
    await expect(page.getByTestId('manual-test-line')).toHaveCount(0)
  })
})
