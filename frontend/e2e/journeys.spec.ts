// qa1: the six main journeys, in a real browser, against the fake backend in support/mockApi.ts.
import { FAKE_TOKEN, WRONG_PASSWORD, mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

test.describe('1. Sign in', () => {
  test('signing in with a username and password lands on Today', async ({ page }) => {
    await mockApi(page, { signedIn: false })
    await page.goto('/')
    await expect(page.getByText('Sign in to your account.')).toBeVisible()
    // This server has sign-up switched off, and the screen says so.
    await expect(page.getByText('Sign-up is closed on this server.')).toBeVisible()

    await page.getByLabel('Username').fill('owner')
    await page.getByLabel('Password').fill('a-test-password')
    const login = page.waitForRequest((r) => r.url().endsWith('/api/v1/auth/login') && r.method() === 'POST')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    expect((await login).postDataJSON()).toEqual({ username: 'owner', password: 'a-test-password' })

    await expect(page).toHaveURL(/\/trademind$/)
    await expect(page.getByText('Market Mode')).toBeVisible()
    expect(await page.evaluate(() => localStorage.getItem('stml.token'))).toBe(FAKE_TOKEN)
  })

  test('a wrong password shows a plain message and stays on the sign-in screen', async ({ page }) => {
    await mockApi(page, { signedIn: false })
    await page.goto('/')
    await page.getByLabel('Username').fill('owner')
    await page.getByLabel('Password').fill(WRONG_PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByText('Incorrect username or password')).toBeVisible()
    await expect(page.getByLabel('Username')).toBeVisible()
    expect(await page.evaluate(() => localStorage.getItem('stml.token'))).toBeNull()
  })

  test('logging out returns to the sign-in screen (owner: from the account menu)', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await expect(page.locator('.tm-topbar').getByRole('button', { name: 'Log out' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Your account and settings' }).click()
    await page.getByRole('menuitem', { name: 'Log out' }).click()
    await expect(page.getByText('Sign in to your account.')).toBeVisible()
  })

  test('logging out returns to the sign-in screen (member: the button on the bar)', async ({ page }) => {
    await mockApi(page, { role: 'member' })
    await openPage(page, '/trademind')
    await page.getByRole('button', { name: 'Log out' }).click()
    await expect(page.getByText('Sign in to your account.')).toBeVisible()
  })
})

test.describe('2. Today', () => {
  test('shows the market mode, the idea counts, holdings needing attention, top ideas and insights', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await expect(page.getByText('Market Mode')).toBeVisible()
    await expect(page.getByText('The market is steady. New trades are allowed within the usual limits.')).toBeVisible()
    for (const title of ["Today's Ideas", 'Holdings Needing Attention', 'Top Ideas', "Today's Insights"]) {
      await expect(page.getByText(title, { exact: true })).toBeVisible()
    }
    // RELIANCE is the one holding the brain flagged (MONITOR); TCS (HOLD) is fine and not listed.
    await expect(page.getByText('Price slipped below its 10-day average.', { exact: true })).toBeVisible()
    await expect(page.locator('[data-card="idea"][data-symbol="INFY"]')).toBeVisible()
    await expect(page.getByText(/practice ideas have finished so far/)).toBeVisible()
  })
})

test.describe('2b. One recommendation card (oa12)', () => {
  for (const path of ['/trademind', '/trademind/opportunities']) {
    test(`every idea on ${path} uses the card, says Experimental, unproven and shows no score as a %`, async ({ page }) => {
      await mockApi(page)
      await openPage(page, path)
      const cards = page.locator('[data-card="idea"]')
      await expect(cards.first()).toBeVisible()
      const n = await cards.count()
      expect(n).toBeGreaterThan(0)
      for (let i = 0; i < n; i++) {
        const card = cards.nth(i)
        await expect(card.getByText('Experimental, unproven', { exact: true })).toBeVisible()
        await expect(card.locator('[data-part="model-status"]')).toContainText('7 of 21')
        // No calibrated chance in these fixtures, so no % at all next to the score.
        await expect(card.locator('[data-part="score"]')).not.toContainText('%')
        await expect(card).not.toContainText(/validated|\bproven\b|profitable|probability/i)
      }
      // INFY is the TRADE: its plan and rupees come from the stock brief.
      const infy = page.locator('[data-card="idea"][data-symbol="INFY"]').first()
      await expect(infy).toContainText('Last exit day: Mon 9 Nov 2026')
      await expect(infy).toContainText('If the stop is hit you lose about ₹402.10')
    })
  }
})

test.describe('3. Stock page', () => {
  test('opening a top idea shows its price chart and the brain decision', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await page.locator('[data-card="idea"][data-symbol="INFY"]').getByRole('link', { name: 'INFY' }).click()
    await expect(page).toHaveURL(/\/trademind\/stock\/INFY$/)
    await expect(page.getByText('INFY · daily price')).toBeVisible()
    await expect(page.getByText('TradeMind Decision')).toBeVisible()
    await expect(page.getByText('Strong upward move with rising volume.').first()).toBeVisible()
    // The tabs switch.
    await page.getByRole('tab', { name: 'Technical' }).click()
    await expect(page.getByRole('tab', { name: 'Technical' })).toHaveAttribute('aria-selected', 'true')
  })
})

test.describe('3b. Why not TRADE, and what changed since yesterday (ux11)', () => {
  test('Today lists what changed; a WATCH idea says why it is not a TRADE and what changed', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    const summary = page.getByTestId('changes-summary')
    await expect(summary).toBeVisible()
    await expect(summary.getByText(/1 decision changed/)).toBeVisible()
    await expect(summary.getByText(/WAIT → TRADE/)).toBeVisible()
    await expect(summary).not.toContainText('%')

    await openPage(page, '/trademind/stock/HDFCBANK')
    const why = page.getByTestId('why-not-trade')
    await expect(why).toBeVisible()
    // The fixture's downgrade reason matches no known rule, so it is shown exactly as stored.
    await expect(why.getByText('Bank sector is already near its limit.')).toBeVisible()
    const change = page.getByTestId('idea-change')
    await expect(change).toHaveAttribute('data-change', 'reason')
    await expect(change.getByText('Still WATCH, but for a different reason than yesterday.')).toBeVisible()
    await expect(change.getByText(/Moved up 1 place in the ranking/)).toBeVisible()
  })
})

test.describe('4. Portfolio', () => {
  test('every Portfolio tab opens, and each says whose money it shows', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await page.getByTestId('nav-portfolio').click()
    const subnav = page.getByTestId('subnav')
    const strip = page.getByTestId('book-strip')

    const tabs: { name: RegExp; url: RegExp; book: 'paper' | 'real'; shows: string }[] = [
      { name: /^Bot/, url: /\/trademind\/positions$/, book: 'paper', shows: 'Position Details' },
      { name: /^Testing/, url: /\/trademind\/testing$/, book: 'paper', shows: 'Closed trades' },
      { name: /^My Zerodha/, url: /\/trademind\/holdings$/, book: 'real', shows: 'Your Zerodha account' },
      { name: /^Paper Overview/, url: /\/trademind\/portfolio$/, book: 'paper', shows: 'Portfolio Overview' },
    ]
    await expect(subnav.getByRole('link')).toHaveCount(tabs.length)
    for (const tab of tabs) {
      await subnav.getByRole('link', { name: tab.name }).click()
      await expect(page).toHaveURL(tab.url)
      await expect(strip).toHaveAttribute('data-book', tab.book)
      await expect(page.getByText(tab.shows, { exact: true })).toBeVisible()
    }
  })
})

test.describe('5. Admin', () => {
  test('the owner can open Admin and every page in it', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await page.getByTestId('nav-admin').click()
    await expect(page).toHaveURL(/\/trademind\/control$/)
    const subnav = page.getByTestId('subnav')
    for (const [name, url] of [
      ['Control', /\/control$/],
      ['Go-live', /\/golive$/],
      ['Risk', /\/risk$/],
      ['System', /\/system$/],
      ['Setup', /\/setup$/],
      ['Observatory', /\/observatory$/],
      ['Alerts', /\/alerts$/],
      ['Jobs', /\/jobs$/],
      ['Plans', /\/plans$/],
    ] as const) {
      await subnav.getByRole('link', { name, exact: true }).click()
      await expect(page).toHaveURL(url)
      await expect(page.locator('.tm-page')).toBeVisible()
    }
    // The account menu lists the same Admin pages.
    await page.getByRole('button', { name: 'Your account and settings' }).click()
    await expect(page.getByRole('menuitem', { name: 'Control' })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: 'Plans' })).toBeVisible()
  })

  test('Risk shows the risk-event log: the same blocked buys the classic Safety page lists (oa2)', async ({ page }) => {
    await mockApi(page)
    const asked = page.waitForRequest((r) => r.url().includes('/api/v1/safety/risk-events'))
    await openPage(page, '/trademind/risk')
    expect(new URL((await asked).url()).searchParams.get('limit')).toBe('100') // the same latest 100 as Safety
    const log = page.getByTestId('risk-event-log')
    await expect(log.getByText('2 events')).toBeVisible()
    await expect(log.locator('tr[data-event]')).toHaveCount(2)
    await expect(log.getByText('Too much in one sector')).toBeVisible()
    await expect(log.getByText('Already holding the maximum number of stocks')).toBeVisible()
  })

  test('Plans opens the existing Plans manager inside TradeMind; /plans still opens the classic screen (oa3)', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind/plans')
    await expect(page.getByRole('heading', { name: 'Free & Pro plans' })).toBeVisible()
    await expect(page.getByTestId('nav-admin')).toHaveClass(/active/)
    await expect(page.getByText('Plan gating is OFF.')).toBeVisible()

    await openPage(page, '/plans')
    await expect(page.getByRole('heading', { name: 'Free & Pro plans' })).toBeVisible()
    await expect(page.getByTestId('nav-admin')).toHaveCount(0)
  })

  test('Alerts: switchable messages have a switch and an explanation, safety messages are always on', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind/alerts')
    const switchable = page.getByTestId('alerts-switchable')
    await expect(switchable.getByLabel('New buy ideas')).toBeChecked()
    await expect(switchable.getByLabel('Practice buys')).not.toBeChecked()
    const always = page.getByTestId('alerts-always-on')
    await expect(always.getByText('Sells and stop-losses')).toBeVisible()
    await expect(always.getByRole('checkbox')).toHaveCount(0)
    await expect(page.getByTestId('alerts-held')).toContainText('1 message is waiting')

    // The explanation opens on tap.
    const ideas = page.locator('[data-alert="trade_ideas"]')
    await expect(ideas.getByText(/finds a stock worth buying/)).toBeHidden()
    await ideas.getByText('What is this?').click()
    await expect(ideas.getByText(/finds a stock worth buying/)).toBeVisible()

    // Save turns on only after a change, and a digest inside quiet hours is caught before saving.
    const save = page.getByRole('button', { name: 'Save', exact: true })
    await expect(save).toBeDisabled()
    await switchable.getByLabel('New buy ideas').uncheck()
    await expect(save).toBeEnabled()
    await page.getByLabel('Send one digest a day').check()
    await page.getByLabel('At').fill('23:00')
    await expect(page.getByText('Pick a digest time outside your quiet hours')).toBeVisible()
    await expect(save).toBeDisabled()
  })

  test('a non-owner sees no Admin and no real-money tab, and owner pages send them back', async ({ page }) => {
    await mockApi(page, { role: 'member' })
    await openPage(page, '/trademind')
    await expect(page.getByTestId('nav-today')).toBeVisible()
    await expect(page.getByTestId('nav-admin')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Your account and settings' })).toHaveCount(0)

    await page.getByTestId('nav-portfolio').click()
    const subnav = page.getByTestId('subnav')
    await expect(subnav.getByRole('link', { name: /^Bot/ })).toBeVisible()
    await expect(subnav.getByRole('link', { name: /^Testing/ })).toHaveCount(0)
    await expect(subnav.getByRole('link', { name: /^My Zerodha/ })).toHaveCount(0)

    // Typing an owner address in: Admin goes back to Today, the real account goes to the paper overview.
    await openPage(page, '/trademind/control')
    await expect(page).toHaveURL(/\/trademind$/)
    await expect(page.getByText('Market Mode')).toBeVisible()
    await openPage(page, '/trademind/holdings')
    await expect(page).toHaveURL(/\/trademind\/portfolio$/)
    await expect(page.getByTestId('book-strip')).toHaveAttribute('data-book', 'paper')
    // Plans: still the classic screen's own owner check, exactly as before (oa3).
    await openPage(page, '/trademind/plans')
    await expect(page.getByText('Owner access required')).toBeVisible()
  })
})

test.describe('5b. Observatory: score vs result (ps5)', () => {
  test('past data shows hit rates; the blind trial shows counts only, never a result', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind/observatory')
    await page.getByRole('tab', { name: 'Results & proof' }).click()
    const card = page.getByTestId('obs-score-bands')
    await expect(page.getByText('Does a higher score really mean better results?')).toBeVisible()
    await expect(card.locator('[data-band="80%-100%"]').first()).toContainText('41% of 429 ideas')
    const trial = card.locator('[data-testid="obs-score-bands-live"][data-period="trial"]')
    await expect(trial).toContainText('counts only')
    await expect(trial.locator('[data-band="80%-100%"]')).toContainText('6 ideas · 2 finished')
    for (const row of await trial.locator('[data-band] .tm-num').allTextContents()) {
      expect(row).not.toContain('%')
    }
  })
})

test.describe('5c. Go-live: the blind trial is sealed', () => {
  test('the stage card shows counts and the sealed sentence, never whether the trial made a profit', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind/golive')
    await expect(page.getByText('12 of 30 brain ideas have finished.', { exact: false })).toBeVisible()
    const plain = page.getByTestId('golive-trial-plain')
    await expect(plain).toContainText("Sealed until the trial's evaluation (blind test): counts only.")
    await expect(plain).toContainText('14 of 15 trial sessions')
    const text = await page.locator('.tm-page').innerText()
    expect(text).not.toMatch(/profit after costs: (yes|no)/i)
    expect(text).not.toMatch(/beats buying every stock: (yes|no)/i)
    expect(text).not.toContain('The forward trial has passed')
  })
})

test.describe('6. Phone width (390 x 844)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  for (const path of ['/trademind', '/trademind/opportunities', '/trademind/stock/INFY', '/trademind/positions', '/trademind/portfolio', '/trademind/control', '/trademind/alerts']) {
    test(`no sideways scrolling on ${path}`, async ({ page }) => {
      await mockApi(page)
      await openPage(page, path)
      await expect(page.locator('.tm-page')).toBeVisible()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, 'page is wider than the phone screen').toBeLessThanOrEqual(0)
    })
  }

  test('the section menu and page tabs work by tapping', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    const sections = page.getByRole('navigation', { name: 'Sections' })
    for (const id of ['today', 'discover', 'portfolio', 'insights', 'admin']) {
      await expect(page.getByTestId(`nav-${id}`)).toBeInViewport()
    }
    await sections.getByTestId('nav-portfolio').tap()
    await expect(page).toHaveURL(/\/trademind\/positions$/)
    // The last page tab may sit off to the side in a sideways-scrolling row; it must still be reachable.
    const last = page.getByTestId('subnav').getByRole('link', { name: /^Paper Overview/ })
    await last.scrollIntoViewIfNeeded()
    await last.tap()
    await expect(page).toHaveURL(/\/trademind\/portfolio$/)
    await expect(page.getByText('Portfolio Overview', { exact: true })).toBeVisible()
  })
})
