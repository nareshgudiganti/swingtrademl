// The side-by-side 5/10/15-day report on the owner-only Horizon picks page: honest labels, no fold model shown as a live one.
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

test.describe('horizon report', () => {
  test('owner sees all rows with plain labels and no verdict before enough days', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/horizon-picks')
    await expect(page.getByText('All three horizons side by side')).toBeVisible()
    await expect(page.locator('[data-horizon-row]')).toHaveCount(3)
    await expect(page.getByText('Evaluation fold model - not used for daily picks')).toBeVisible()
    await expect(page.getByText('Fold models are not daily models.')).toBeVisible()
    await expect(page.getByText('Software tests passing does not prove a model works', { exact: false })).toBeVisible()
    await expect(page.getByText('Not enough days to judge.').first()).toBeVisible()
    await expect(page.locator('[data-model-role="final"]')).toHaveCount(0)
    await expect(page.locator('[data-model-role="fold"]')).toHaveCount(1)
    await expect(page.getByText('Not qualified yet.').first()).toBeVisible()
  })
})
