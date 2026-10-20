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

  test('logging out returns to the sign-in screen', async ({ page }) => {
    await mockApi(page)
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
    await expect(page.getByRole('row', { name: /INFY/ })).toBeVisible()
    await expect(page.getByText(/practice ideas have finished so far/)).toBeVisible()
  })
})

test.describe('3. Stock page', () => {
  test('opening a top idea shows its price chart and the brain decision', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await page.getByRole('row', { name: /INFY/ }).click()
    await expect(page).toHaveURL(/\/trademind\/stock\/INFY$/)
    await expect(page.getByText('INFY · daily price')).toBeVisible()
    await expect(page.getByText('TradeMind Decision')).toBeVisible()
    await expect(page.getByText('Strong upward move with rising volume.').first()).toBeVisible()
    // The tabs switch.
    await page.getByRole('tab', { name: 'Technical' }).click()
    await expect(page.getByRole('tab', { name: 'Technical' })).toHaveAttribute('aria-selected', 'true')
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
    ] as const) {
      await subnav.getByRole('link', { name, exact: true }).click()
      await expect(page).toHaveURL(url)
      await expect(page.locator('.tm-page')).toBeVisible()
    }
    // The account menu lists the same Admin pages.
    await page.getByRole('button', { name: 'Your account and settings' }).click()
    await expect(page.getByRole('menuitem', { name: 'Control' })).toBeVisible()
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
  })
})

test.describe('6. Phone width (390 x 844)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  for (const path of ['/trademind', '/trademind/stock/INFY', '/trademind/positions', '/trademind/portfolio', '/trademind/control', '/trademind/alerts']) {
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
