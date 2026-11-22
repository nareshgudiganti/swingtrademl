// The brain is on but has no finished run (a new install): /brain/runs/latest answers 404. Refetching that
// answer must not look like a first load: BrainGate would drop the page, whose own query refetches on mount,
// and the two would loop.
import type { Page } from '@playwright/test'

import latestRun from './fixtures/brain-latest-run.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

type Answer = { status: number; body: object; delay?: number }
const NO_RUN: Answer = { status: 404, body: { detail: 'The brain has not run yet.' } }

async function latestAnswers(page: Page, first: Answer) {
  const state = { answer: first, calls: 0 }
  await page.route('**/api/v1/brain/runs/latest**', async (route) => {
    state.calls++
    const { status, body, delay = 100 } = state.answer
    await new Promise((resolve) => setTimeout(resolve, delay))
    await route.fulfill({ status, json: body })
  })
  return state
}

/** What happens when the person comes back to the tab. */
const refocus = (page: Page) => page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))

const runButton = (page: Page) => page.getByRole('button', { name: 'Run the brain now', exact: true })

test.describe('brain on, no run yet', () => {
  test('System opens and does not keep asking for the latest run', async ({ page }) => {
    const latest = await noRunYet(page)
    await openPage(page, '/trademind/system')
    await page.waitForTimeout(3000) // a loop needs time to show itself
    expect(latest.calls).toBeLessThanOrEqual(6)
    await expect(runButton(page)).toBeVisible()
  })

  test('a refetch keeps the open page on screen', async ({ page }) => {
    const latest = await noRunYet(page)
    await openPage(page, '/trademind/golive')
    const loading = page.getByText(/Loading the trading controls/)
    await expect(loading).toHaveCount(0)
    await page.waitForTimeout(1000)
    latest.answer = { ...NO_RUN, delay: 3000 }
    const before = latest.calls
    await refocus(page)
    await expect.poll(() => latest.calls).toBeGreaterThan(before)
    await page.waitForTimeout(500) // inside the refetch
    expect(await loading.count()).toBe(0)
  })

  test('the first run replaces "no run yet"', async ({ page }) => {
    const latest = await noRunYet(page)
    await openPage(page, '/trademind')
    await expect(page.getByText('No run yet', { exact: true })).toBeVisible()
    latest.answer = { status: 200, body: latestRun }
    await refocus(page)
    await expect(page.getByText('Market Mode')).toBeVisible()
  })

  test('a server error after "no run yet" is shown as an error', async ({ page }) => {
    const latest = await noRunYet(page)
    await openPage(page, '/trademind')
    await expect(page.getByText('No run yet', { exact: true })).toBeVisible()
    latest.answer = { status: 500, body: { detail: 'Internal server error' } }
    await refocus(page)
    await expect(page.getByText('Could not reach the brain')).toBeVisible()
  })

  test('the first load still shows Loading', async ({ page }) => {
    await mockApi(page)
    await latestAnswers(page, { status: 200, body: latestRun, delay: 2500 })
    await page.goto('/trademind')
    await expect(page.getByText(/Loading the brain/)).toBeVisible()
    await expect(page.getByText('Market Mode')).toBeVisible()
  })

  test('a switched-off brain is still shown as off', async ({ page }) => {
    await noRunYet(page)
    await page.route('**/api/v1/brain/health**', (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }))
    await openPage(page, '/trademind/system')
    await expect(runButton(page)).toHaveCount(0)
    await expect(page.getByText(/switched off/i).first()).toBeVisible()
  })
})

async function noRunYet(page: Page) {
  await mockApi(page)
  return latestAnswers(page, NO_RUN)
}
