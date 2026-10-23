// ux10: the model score is a ranking, never a chance. No TradeMind page may show it with a % sign
// ("Model score 72%", "Score 70%-80%") or call it a probability. Where the day's ideas are known it reads as
// a place in the ranking ("Rank 1 of 3 today"); otherwise as a plain number that says it is not a chance.
// The calibrated "Est. chance" (honest_score) is a real measured chance and is allowed to use %.
import type { Page } from '@playwright/test'

import brainLatestRun from './fixtures/brain-latest-run.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

/** "score" directly followed by a number with a % sign ("Model score: 72%", "Score 70%-80%"). Text such as
 *  "a similar score really went up 8%" is about the price move, so only a number right after "score" counts. */
const SCORE_AS_PERCENT = /\bscore\b[:\s]*(?:of\s+)?\d+(?:\.\d+)?\s*%/i
const SCORE_AS_CHANCE = /score[^\n]{0,30}\b(probability|likelihood|odds)\b/i

async function expectNoScoreAsPercent(page: Page) {
  const text = await page.locator('body').innerText()
  expect(text).not.toMatch(SCORE_AS_PERCENT)
  expect(text).not.toMatch(SCORE_AS_CHANCE)
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('stock page shows the idea as a rank among today’s ideas', async ({ page }) => {
  await openPage(page, '/trademind/stock/INFY')
  await expect(page.getByText('Rank 1 of 3 today').first()).toBeVisible()
  await expectNoScoreAsPercent(page)
  await page.getByRole('tab', { name: 'AI Analysis' }).click()
  await expect(page.getByText('Rank 1 of 3 today by model score')).toBeVisible()
  await expectNoScoreAsPercent(page)
})

test('bot positions show a holding’s score as a plain number, not a chance', async ({ page }) => {
  await openPage(page, '/trademind/positions/TCS')
  await expect(page.getByText('Model score 66', { exact: true })).toBeVisible()
  await expectNoScoreAsPercent(page)
})

test('watchlist shows each idea’s rank', async ({ page }) => {
  await openPage(page, '/trademind/watchlist')
  await expect(page.getByRole('cell', { name: 'Rank 1 of 3 today' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Rank 3 of 3 today' })).toBeVisible()
  await expectNoScoreAsPercent(page)
})

test('version 1 picks show a rank, and the details say the number is not a chance', async ({ page }) => {
  await openPage(page, '/trademind/records')
  await page.getByRole('tab', { name: "Version 1's picks" }).click()
  await expect(page.getByRole('cell', { name: 'Rank 1 of 2 today' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Rank 2 of 2 today' })).toBeVisible()
  await expect(page.getByRole('cell', { name: /^72%$/ })).toHaveCount(0)
  await page.getByRole('button', { name: 'Details' }).first().click()
  await expect(page.getByText('Model score 72 (a ranking number, not a chance of profit)')).toBeVisible()
  await expectNoScoreAsPercent(page)
})

test('learning report shows score bands and the average score without %', async ({ page }) => {
  await openPage(page, '/trademind/learn')
  await expect(page.getByRole('columnheader', { name: 'Average model score' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '64', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '64%' })).toHaveCount(0)
  await expect(page.getByRole('cell', { name: '60-70', exact: true })).toBeVisible()
  await expectNoScoreAsPercent(page)
})

test('observatory score bands have no % sign', async ({ page }) => {
  await openPage(page, '/trademind/observatory')
  await page.getByRole('tab', { name: 'Results & proof' }).click()
  await expect(page.getByText('Score 70-80').first()).toBeVisible()
  await expectNoScoreAsPercent(page)
})

// The brain's stored lines write the raw score with a % ("Model score 44% is below the buy level 55%."). The brain
// is frozen, so the screens take the % off. Later routes win in Playwright, so this replaces the fixture run.
async function withStoredScoreLine(page: Page) {
  const run = structuredClone(brainLatestRun)
  for (const d of run.decisions) {
    if (d.symbol === 'ITC') d.reasons = ['Model score 44% is below the buy level 55%.']
  }
  await page.route(
    (url) => url.pathname === '/api/v1/brain/runs/latest',
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(run) }),
  )
}

for (const path of ['/trademind/stock/ITC', '/trademind/watchlist']) {
  test(`${path} shows the brain's stored score line without a %`, async ({ page }) => {
    await withStoredScoreLine(page)
    await openPage(page, path)
    await expect(page.getByText('Model score 44 is below the buy level 55.').first()).toBeVisible()
    await expectNoScoreAsPercent(page)
  })
}

test('setup models tab groups predictions by model score without %', async ({ page }) => {
  await openPage(page, '/trademind/setup')
  await page.getByRole('tab', { name: 'Models' }).click()
  await expect(page.getByText('Does a higher model score really work out more often?')).toBeVisible()
  await expectNoScoreAsPercent(page)
})

for (const path of [
  '/trademind',
  '/trademind/opportunities',
  '/trademind/dashboard',
  '/trademind/portfolio',
  '/trademind/positions',
  '/trademind/ai',
  '/trademind/risk',
  '/trademind/market',
  '/trademind/golive',
  '/trademind/holdings',
]) {
  test(`${path} never shows the model score as a %`, async ({ page }) => {
    await openPage(page, path)
    await expect(page.getByTestId('nav-today')).toBeVisible()
    await expect(page.locator('body')).not.toBeEmpty()
    await expectNoScoreAsPercent(page)
  })
}
