// #227 / #281 acceptance: the Discover screen (/trademind/opportunities, new look) in a real browser against the fake
// backend (e2e/support/mockApi.ts). Nothing here reaches production or the live stack.
//
// The run served here is e2e/fixtures/discover-run.json (7 ideas, all four words) and the sector map is
// e2e/fixtures/discover-sectors.json. Both are NEW fixture files; the shared fixtures are untouched.
import type { Page } from '@playwright/test'

import brainHealth from './fixtures/brain-health.json' with { type: 'json' }
import discoverRun from './fixtures/discover-run.json' with { type: 'json' }
import discoverSectors from './fixtures/discover-sectors.json' with { type: 'json' }
import { mockApi, type Role } from './support/mockApi'
import { expect, test } from './support/test'

const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })
const pct = (f: number) => Math.round(f * 10000) / 100

type Rules = { brain_plan: { target_pct: number; stop_pct: number; half_out_pct: number; max_sessions: number } }

type Opts = {
  role?: Role
  run?: unknown
  /** The sector map: a map, or 'refused' (an account that may not read it). */
  sectors?: Record<string, string | null> | 'refused'
  health?: unknown
  rules?: unknown
}

/** Fake backend + new look, with the Discover run, the sector map and (optionally) other answers on top. */
async function setup(page: Page, o: Opts = {}) {
  await mockApi(page, { role: o.role ?? 'owner' })
  await page.addInitScript(() => localStorage.setItem('tm-look', 'new'))
  // Registered after mockApi, so these win.
  await page.route(
    (u) => u.pathname === '/api/v1/brain/runs/latest',
    (r) => r.fulfill(json(o.run ?? discoverRun)),
  )
  await page.route(
    (u) => u.pathname === '/api/v1/market-data/sectors',
    (r) => (o.sectors === 'refused' ? r.fulfill(json({ detail: 'Not in your plan.' }, 403)) : r.fulfill(json(o.sectors ?? discoverSectors))),
  )
  if (o.health) await page.route((u) => u.pathname === '/api/v1/brain/health', (r) => r.fulfill(json(o.health)))
  if (o.rules) await page.route((u) => u.pathname === '/api/v1/config/trading-rules', (r) => r.fulfill(json(o.rules)))
}

async function openDiscover(page: Page) {
  await page.goto('/trademind/opportunities')
  await expect(page.locator('[data-page="discover-new"]')).toBeVisible()
}

const table = (page: Page) => page.getByTestId('discover-table')
const rowOf = (page: Page, symbol: string) =>
  table(page).locator('tbody tr').filter({ has: page.getByText(symbol, { exact: true }) })
/** The stock symbols in the table, top to bottom. */
const symbolsShown = (page: Page) => table(page).locator('tbody tr a.tmn-w2-stock b').allTextContents()
const pill = (page: Page, name: RegExp) => page.getByTestId('discover-filters').getByRole('button', { name })

test.describe('Discover (#227)', () => {
  test('the list comes from the stored run, with all four words and their counts', async ({ page }) => {
    await setup(page)
    await openDiscover(page)

    await expect(pill(page, /^All/)).toContainText('7')
    await expect(pill(page, /^BUY/)).toContainText('2')
    await expect(pill(page, /^WATCH/)).toContainText('2')
    await expect(pill(page, /^WAIT/)).toContainText('2')
    await expect(pill(page, /^AVOID/)).toContainText('1')

    // Every idea of the run (not the holdings), best word first and then by score.
    await expect(table(page)).toBeVisible()
    expect(await symbolsShown(page)).toEqual(['INFY', 'LT', 'WIPRO', 'HDFCBANK', 'SBIN', 'ITC', 'TATASTEEL'])
    await expect(table(page)).not.toContainText('TCS') // a holding in the same run is not an idea
    await expect(page.locator('[data-page="discover-new"]')).toContainText('Brain’s run on')
    await expect(page.getByTestId('no-trade-reason')).toHaveCount(0) // there are TRADE ideas: nothing to explain
  })

  test('filtering by word, by sector and by search narrows the list', async ({ page }) => {
    await setup(page)
    await openDiscover(page)
    await expect(table(page)).toBeVisible()

    await pill(page, /^WATCH/).click()
    await expect(pill(page, /^WATCH/)).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(() => symbolsShown(page)).toEqual(['WIPRO', 'HDFCBANK'])
    await pill(page, /^AVOID/).click()
    await expect.poll(() => symbolsShown(page)).toEqual(['TATASTEEL'])
    await pill(page, /^All/).click()

    // Sector filter: listed from the sector map, only sectors that have an idea.
    const sector = page.getByTestId('sector-filter')
    await expect(sector.locator('option')).toHaveText(['All sectors', 'Banks', 'Capital goods', 'FMCG', 'IT', 'Metals'])
    await sector.selectOption('Banks')
    await expect.poll(() => symbolsShown(page)).toEqual(['HDFCBANK', 'SBIN'])
    // Word and sector together.
    await pill(page, /^WAIT/).click()
    await expect.poll(() => symbolsShown(page)).toEqual(['SBIN'])
    await pill(page, /^BUY/).click()
    await expect(page.locator('[data-state="empty"]')).toHaveText('No stocks match these filters.')
    await pill(page, /^All/).click()
    await sector.selectOption('')

    // Search: any letter case, part of the symbol.
    const search = page.getByRole('searchbox', { name: 'Find a stock in this list' })
    await search.fill('inf')
    await expect.poll(() => symbolsShown(page)).toEqual(['INFY'])
    await search.fill('  Tata ')
    await expect.poll(() => symbolsShown(page)).toEqual(['TATASTEEL'])
    await search.fill('zzz')
    await expect(page.locator('[data-state="empty"]')).toHaveText('No stocks match these filters.')
    await search.fill('')
    await expect.poll(() => symbolsShown(page)).toHaveLength(7)
  })

  test('a sector map that is refused hides the sector filter and nothing else breaks', async ({ page }) => {
    await setup(page, { role: 'member', sectors: 'refused' })
    await openDiscover(page)
    await expect(table(page)).toBeVisible()
    await expect(page.getByTestId('sector-filter')).toHaveCount(0)
    expect(await symbolsShown(page)).toHaveLength(7)
    await expect(page.locator('[data-feature="classic-strategy-signals"]')).toHaveCount(0)
  })

  test('a non-TRADE row says where it stopped (from its stored reason) and carries no plan', async ({ page }) => {
    await setup(page)
    await openDiscover(page)
    await expect(table(page)).toBeVisible()

    await expect(rowOf(page, 'INFY')).toContainText('Passed')
    await expect(rowOf(page, 'WIPRO')).toContainText('Situation')
    await expect(rowOf(page, 'SBIN')).toContainText('Model check')
    await expect(rowOf(page, 'TATASTEEL')).toContainText('Similar cases')
    // Nothing stored says why: it says so, it does not guess a step.
    await expect(rowOf(page, 'ITC')).toContainText('Not recorded')
    for (const s of ['WIPRO', 'HDFCBANK', 'SBIN', 'ITC', 'TATASTEEL']) {
      await expect(rowOf(page, s)).not.toContainText('Passed')
      await expect(rowOf(page, s)).not.toContainText('₹') // no buy zone, target or stop on a row that is not a buy
    }
  })

  test('a TRADE idea opens its plan (stock page, Full analysis), and the plan wording follows the served trading rules', async ({ page }) => {
    await setup(page)
    await openDiscover(page)
    const rules: Rules = await page.evaluate(async () => (await fetch('/api/v1/config/trading-rules')).json())
    const p = rules.brain_plan

    await rowOf(page, 'INFY')
      .getByRole('link', { name: /AI analysis/ })
      .click()
    await page.getByRole('link', { name: /Full analysis/ }).click()
    const plan = page.getByTestId('plan-ladder')
    await expect(plan).toBeVisible()
    await expect(plan).toContainText('The plan for this buy.')
    await expect(plan).toContainText(`Sold within ${p.max_sessions} trading days`)
    await expect(plan).toContainText('₹1,480 – ₹1,495') // the stored buy zone
    await expect(plan).toContainText('₹1,610') // the stored target
    await expect(plan).toContainText('₹1,430') // the stored stop
    await expect(plan).toContainText(`+${pct(p.half_out_pct)}% · lock in`)
    await expect(plan).toContainText(`+${Math.round(pct(p.target_pct))}% · sell rest`)
    await expect(plan).toContainText(`${-Math.round(pct(p.stop_pct))}% · get out`)
  })

  test('a changed half-way level on the server changes both the label and the price', async ({ page }) => {
    test.fail(true, 'Defect: PlanLadder (stockParts.tsx) prices "Sell half" at a hard-coded mid * 1.05 but labels it from the served half_out_pct.')
    await mockApi(page) // only to read the served rules
    await page.goto('/trademind')
    const base: Rules & Record<string, unknown> = await page.evaluate(async () => (await fetch('/api/v1/config/trading-rules')).json())
    const rules = { ...base, brain_plan: { ...base.brain_plan, half_out_pct: 0.06 } }

    const fresh = await page.context().newPage()
    await setup(fresh, { rules })
    await fresh.goto('/trademind/stock/INFY/analysis')
    const plan = fresh.getByTestId('plan-ladder')
    await expect(plan).toContainText('+6% · lock in')
    // The middle of the 1,480 - 1,495 buy zone is 1,487.5; +6% is 1,576.75 (+5% would be 1,561.88).
    await expect(plan).toContainText('₹1,576.75')
  })

  test('a TRADE row on Discover shows its plan (buy zone, target, stop)', async ({ page }) => {
    test.fail(true, 'Gap vs requirements section 1: the Discover table has no plan columns; the plan is only one tap away on the stock page.')
    await setup(page)
    await openDiscover(page)
    const row = rowOf(page, 'INFY')
    await expect(row).toContainText('1,480')
    await expect(row).toContainText('1,610')
    await expect(row).toContainText('1,430')
  })

  test('a score is a ranking, never a chance or probability of profit', async ({ page }) => {
    await setup(page)
    await openDiscover(page)
    await expect(table(page)).toBeVisible()

    // Each row: the place in the ranking and a whole-number score, no % sign, no chance wording.
    const cells = await table(page)
      .locator('tbody tr')
      .evaluateAll((trs) =>
        trs.map((tr) => ({ place: tr.querySelectorAll('td')[0]?.textContent ?? '', score: tr.querySelectorAll('td')[3]?.textContent ?? '' })),
      )
    expect(cells.map((c) => c.place)).toEqual(['1', '2', '3', '4', '5', '6', '7'])
    expect(cells.map((c) => c.score)).toEqual(['71', '69', '66', '58', '52', '44', '31'])
    await expect(table(page)).not.toContainText(/chance|probab|likel|odds|%/i)
    // The score column says what it is on hover, and the page says what it is not.
    await expect(table(page).getByRole('columnheader', { name: /Score/ })).toHaveAttribute('title', /not a chance of making money/)
    await expect(page.getByTestId('discover-foot')).toContainText('it is not a chance of profit')
    // The same on the slide view.
    await page.getByTestId('layout-slides').click()
    const slides = page.getByTestId('discover-slides')
    await expect(slides).toBeVisible()
    await expect(slides).not.toContainText(/chance|probab|likel|odds|%/i)
  })

  test('a run with no stocks says so instead of showing an empty table', async ({ page }) => {
    await setup(page, { run: { ...discoverRun, counts: {}, decisions: discoverRun.decisions.filter((d) => d.kind === 'holding') } })
    await openDiscover(page)
    await expect(pill(page, /^All/)).toContainText('0')
    await expect(page.locator('[data-state="empty"]')).toHaveText("The brain's last run had no stocks to look at, so there are no ideas.")
    await expect(page.getByTestId('sector-filter')).toHaveCount(0)
    await expect(table(page)).toHaveCount(0)
  })

  test('a careful market with no BUY idea says why, and never invents one', async ({ page }) => {
    const run = {
      ...discoverRun,
      banner: { mode: 'NO_NEW_TRADES', headline: 'The market fell sharply.' },
      decisions: discoverRun.decisions.map((d) =>
        d.word === 'TRADE' ? { ...d, word: 'WATCH', entry_low: null, entry_high: null, target: null, stop: null, qty: 0 } : d,
      ),
    }
    await setup(page, { run })
    await openDiscover(page)
    await expect(pill(page, /^BUY/)).toContainText('0')
    await expect(page.getByTestId('no-trade-reason')).toContainText('"No new trades" mode')
    await expect(page.getByTestId('no-trade-reason')).toContainText('The market fell sharply.')
    await pill(page, /^BUY/).click()
    await expect(page.locator('[data-state="empty"]')).toBeVisible()
    await expect(table(page)).toHaveCount(0)
  })

  test('when the newest run did not finish, the page names the older run it shows', async ({ page }) => {
    const health = {
      ...brainHealth,
      last_run: { run_id: 'run-2026-10-17', kind: 'nightly', started_at: '2026-10-17T12:30:00Z', status: 'failed', ms: 900, error: 'boom' },
    }
    await setup(page, { health })
    await openDiscover(page)
    const note = page.getByTestId('run-failed-note')
    await expect(note).toContainText('did not finish')
    await expect(note).toContainText('This page shows the earlier run from')
    // The list is still the stored run, unchanged.
    await expect(table(page)).toBeVisible()
    expect(await symbolsShown(page)).toHaveLength(7)
    await expect(pill(page, /^BUY/)).toContainText('2')
  })

  test('member and tester see the same ideas and no owner controls', async ({ page }) => {
    for (const role of ['member', 'tester'] as const) {
      const p = await page.context().newPage()
      await setup(p, { role })
      await openDiscover(p)
      await expect(table(p)).toBeVisible()
      expect(await symbolsShown(p)).toHaveLength(7)
      await expect(p.getByTestId('discover-filters')).toBeVisible()
      await expect(p.locator('[data-page="discover-new"]')).not.toContainText(/kill switch|approve|My Zerodha|real money/i)
    }
  })
})

test.describe('Discover at phone width (390 x 844)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('the page does not scroll sideways', async ({ page }) => {
    await setup(page, { role: 'member' })
    await openDiscover(page)
    await expect(table(page)).toBeAttached()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, 'page is wider than the phone screen').toBeLessThanOrEqual(0)
  })
})
