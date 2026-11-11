// The score trail and the brain's score are different models' numbers and must never share a line.
// KEC on 2026-11-10 (real values): the daily trail comes from the small-cap model and ends 80 → 81; the brain's
// score for the held stock is 77 and its stored lines name no model. A model switch inside a trail breaks the line.
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import type { Page } from '@playwright/test'

import brainLatestRun from './fixtures/brain-latest-run.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

const SMALL = 'swing_classifier_smallcap:v1'
const point = (date: string, score: number, model: string | null = SMALL) => ({ date, score, band: 'strong', model_version: model })

const KEC_TRAIL = [
  point('2026-11-03', 0.9342),
  point('2026-11-04', 0.8565),
  point('2026-11-05', 0.8579),
  point('2026-11-06', 0.8227),
  point('2026-11-09', 0.7986),
  point('2026-11-10', 0.8093),
]

const kecHolding = {
  ...(brainLatestRun.decisions.find((d) => d.kind === 'holding') as object),
  id: 9001,
  symbol: 'KEC',
  word: 'MONITOR',
  reasons: ['The market is careful and this stock is falling — watch it closely.', 'On track: ₹334, +3.7% since buying.'],
  confidence: 0.7653723415976902,
  honest_score: null,
}

async function serveKec(page: Page, trail: ReturnType<typeof point>[]) {
  await mockApi(page)
  // These parts belong to the new look (classic, the default, does not draw them).
  await page.addInitScript(() => localStorage.setItem('tm-look', 'new'))
  // Registered after mockApi, so these answer first.
  await page.route('**/api/v1/ml/score-trail/KEC', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ symbol: 'KEC', score_trail: trail, score_band: 'strong', last_score: trail.at(-1)?.score }) }),
  )
  await page.route('**/api/v1/brain/runs/latest**', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ...brainLatestRun, started_at: '2026-11-10T10:20:00Z', decisions: [...brainLatestRun.decisions, kecHolding] }),
    }),
  )
}

const SHOTS = process.env.E2E_SHOT_DIR
async function shot(page: Page, name: string) {
  if (!SHOTS) return
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true })
}

test('KEC: the trail ends 80 → 81 and the brain’s 77 is shown on its own', async ({ page }) => {
  await serveKec(page, KEC_TRAIL)
  await openPage(page, '/trademind/stock/KEC')
  const glance = page.getByTestId('stock-glance')
  await expect(glance).toBeVisible()
  // The big number is the brain's, and the card says which series the bars are.
  await expect(glance.getByText('5-day model score')).toBeVisible()
  await expect(glance.locator('.sp-big').first()).toHaveText('77')
  await expect(page.getByTestId('glance-score-model')).toContainText('Big number: brain, model not recorded.')
  await expect(page.getByTestId('glance-score-model')).toContainText('Bars: daily check, swing_classifier_smallcap v1.')
  await shot(page, 'kec-stock')

  await openPage(page, '/trademind/stock/KEC/analysis')
  const monitor = page.getByTestId('score-monitor')
  await expect(monitor).toBeVisible()
  await expect(monitor.getByTestId('score-monitor-day')).toHaveCount(6) // wait for the trail to load
  const days = await monitor.locator('[data-testid="score-monitor-day"] strong').allInnerTexts()
  expect(days.slice(-2)).toEqual(['80', '81']) // the trail ends 80 → 81
  expect(days).not.toContain('77') // the brain's score is never one of the days
  await expect(monitor.getByTestId('score-monitor-brain')).toContainText('Brain’s score today: 77')
  await expect(monitor.getByTestId('score-monitor-brain')).toContainText('model not recorded')
  await expect(monitor.getByTestId('score-monitor-break')).toHaveCount(0)
  const chart = page.getByTestId('score-chart')
  await expect(chart).toContainText('Model: swing_classifier_smallcap v1')
  await expect(chart).not.toContainText('Buy level')
  await expect(chart.locator('em')).toHaveText('81')
  await shot(page, 'kec-analysis')

  const text = await page.locator('body').innerText()
  expect(text).not.toMatch(/\bscore\b[:\s]*(?:of\s+)?\d+(?:\.\d+)?\s*%/i)
})

test('a model switch inside a trail breaks the line and counts no move across it', async ({ page }) => {
  const OLD = 'swing_classifier_smallcap:v1'
  const NEW = 'swing_classifier_smallcap:v2'
  await serveKec(page, [
    point('2026-11-03', 0.5, OLD),
    point('2026-11-04', 0.52, OLD),
    point('2026-11-05', 0.55, OLD),
    point('2026-11-06', 0.8, NEW),
    point('2026-11-09', 0.82, NEW),
  ])
  await openPage(page, '/trademind/stock/KEC/analysis')
  const monitor = page.getByTestId('score-monitor')
  await expect(monitor.getByTestId('score-monitor-break')).toHaveCount(1)
  await expect(monitor.getByTestId('score-monitor-break')).toContainText('model changed: swing_classifier_smallcap v2')
  // Moves are counted inside each model only: 50→52, 52→55 (old) and 80→82 (new). 55→80 is never a move.
  const moves = await monitor.locator('.sp-pos, .sp-neg').allInnerTexts()
  expect(moves.map((m) => m.replace(/\s+/g, ' ').trim())).toEqual(['▲ 2', '▲ 3', '▲ 2'])
  await expect(page.getByTestId('score-chart')).toContainText('came from a different model and are left out')
  await expect(page.getByTestId('score-chart').locator('i')).toHaveCount(2)
  await shot(page, 'kec-model-switch')
})
