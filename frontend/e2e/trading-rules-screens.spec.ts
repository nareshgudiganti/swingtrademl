// #416 acceptance: Today, Portfolio and Groww Tracker show the same trading numbers GET /config/trading-rules serves,
// and a changed server value changes the screen. Fake backend only (e2e/support/mockApi.ts): nothing reaches production.
import type { Page } from '@playwright/test'

import { mockApi } from './support/mockApi'
import { expect, test } from './support/test'

type Rules = {
  brain_plan: { target_pct: number; stop_pct: number; half_out_pct: number; max_sessions: number }
  risk_limits: { max_drawdown_pct: number }
}
const pct = (f: number) => Math.round(f * 10000) / 100

const tracker = (days: number) => ({
  as_of: '2026-11-07',
  horizon_days: days,
  items: [
    {
      symbol: 'KEI', name: 'KEI Ltd', added_at: '2026-10-28T05:00:00Z', note: null, buy_price: 4210, bought_on: '2026-10-28',
      quantity: 10, invested: 42100, profit_amount: 3020, entry_price: 4210, entry_source: 'your_price', last_price: 4512,
      return_pct: 7.2, today_pct: 0.7, days_done: 9, score_today: 92, score_prev: 90, score_delta: 2, score_first: 84,
      scores: [{ date: '2026-10-28', score: 84 }, { date: '2026-10-29', score: 92 }],
      closes: [{ date: '2026-10-28', close: 4210 }, { date: '2026-10-29', close: 4512 }], state: 'target',
    },
  ],
})

async function setup(page: Page, override?: Rules & Record<string, unknown>) {
  await mockApi(page, { role: 'member' })
  await page.addInitScript(() => localStorage.setItem('tm-look', 'new'))
  // Registered after mockApi, so these win.
  await page.route((u) => u.pathname === '/api/v1/me/watchlist/tracker', (r) =>
    r.fulfill({ contentType: 'application/json', body: JSON.stringify(tracker(override ? override.brain_plan.max_sessions : 15)) }),
  )
  if (override) {
    await page.route((u) => u.pathname === '/api/v1/config/trading-rules', (r) =>
      r.fulfill({ contentType: 'application/json', body: JSON.stringify(override) }),
    )
  }
}

/** What the endpoint answers to this browser, read the way the app reads it. */
async function served(page: Page): Promise<Rules & Record<string, unknown>> {
  return page.evaluate(async () => (await fetch('/api/v1/config/trading-rules')).json())
}

const words = (r: Rules) => {
  const p = r.brain_plan
  return { target: pct(p.target_pct), stop: pct(p.stop_pct), half: pct(p.half_out_pct), days: p.max_sessions, dd: pct(r.risk_limits.max_drawdown_pct) }
}

async function checkScreens(page: Page, r: Rules) {
  const w = words(r)

  await page.goto('/trademind/groww-tracker')
  const tracker$ = page.locator('[data-page="groww-tracker"]')
  await expect(tracker$).toContainText(`The app's ${w.days}-day plan`)
  await expect(tracker$).toContainText(`+${w.target}% target, −${w.stop}% stop, sell half at +${w.half}%, and be out within ${w.days} trading days`)
  await expect(page.getByTestId('tracker-detail')).toContainText(`(−${w.stop}%) / `)
  await expect(page.getByTestId('tracker-detail')).toContainText(`(+${w.target}%)`)

  await page.goto('/trademind/portfolio')
  await expect(page.getByText(`Sell half at +${w.half}%, the rest at the +${w.target}% target`)).toBeVisible()
  await expect(page.getByText(`Sell within ${w.days} trading days`)).toBeVisible()
  await expect(page.getByText(`Stop all new buys if the account falls ${w.dd}% from its peak`)).toBeVisible()

  await page.goto('/trademind')
  await expect(page.getByText(`every trade in the Brain's ${w.days}-day trial has a −${w.stop}% stop, a +${w.target}% target and a ${w.days}-trading-day limit`)).toBeVisible()
  await expect(page.getByText(`The ${w.days}-day model is experimental and not yet proven.`)).toBeVisible()
}

test.describe('#416 trading rules on the screens', () => {
  test('Today, Portfolio and Groww Tracker show the numbers the endpoint serves', async ({ page }) => {
    await setup(page)
    await page.goto('/trademind')
    const r = await served(page)
    // Guard against a fixture that quietly stops matching what the screens were written for.
    expect(words(r)).toEqual({ target: 8, stop: 4, half: 5, days: 15, dd: 15 })
    await checkScreens(page, r)
  })

  test('a changed endpoint value changes the text on all three screens', async ({ page }) => {
    const base = await (async () => {
      await mockApi(page, { role: 'member' })
      await page.goto('/trademind')
      return served(page)
    })()
    const changed = {
      ...base,
      brain_plan: { target_pct: 0.09, stop_pct: 0.03, half_out_pct: 0.06, max_sessions: 12 },
      risk_limits: { max_drawdown_pct: 0.2 },
    }
    const ctx = page.context()
    const fresh = await ctx.newPage()
    await setup(fresh, changed)
    await fresh.goto('/trademind')
    const r = await served(fresh)
    expect(words(r)).toEqual({ target: 9, stop: 3, half: 6, days: 12, dd: 20 })
    await checkScreens(fresh, r)
    await expect(fresh.locator('body')).not.toContainText('+8% target')
  })
})
