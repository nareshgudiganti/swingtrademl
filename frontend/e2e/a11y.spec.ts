// qa10: accessibility and phone checks. axe scans each main page in light and dark, failing on serious or
// critical problems that are not on the known-debt list (a11y-allowlist.json), and the primary menu is
// checked for finger-sized tap targets at phone width.
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'

import allowlist from './a11y-allowlist.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

type Allowed = { rule: string; page: string; todo: string }
const ALLOWED = allowlist.allowed as Allowed[]

/** page key -> how to open it and the text that proves it finished drawing. */
const SCANNED: Record<string, { open: (page: Page) => Promise<void>; ready: string }> = {
  'front-page': {
    open: async (page) => {
      await mockApi(page, { signedIn: false })
      await page.goto('/')
    },
    ready: 'Join the trial',
  },
  'sign-in': {
    open: async (page) => {
      await mockApi(page, { signedIn: false })
      await page.goto('/signin')
    },
    ready: 'Welcome back',
  },
  today: { open: (page) => signedIn(page, '/trademind'), ready: 'Market Mode' },
  stock: { open: (page) => signedIn(page, '/trademind/stock/INFY'), ready: 'TradeMind Decision' },
  'portfolio-bot': { open: (page) => signedIn(page, '/trademind/positions'), ready: 'Position Details' },
  'portfolio-testing': { open: (page) => signedIn(page, '/trademind/testing'), ready: 'Closed trades' },
  'portfolio-real': { open: (page) => signedIn(page, '/trademind/holdings'), ready: 'Your Zerodha account' },
  'portfolio-overview': { open: (page) => signedIn(page, '/trademind/portfolio'), ready: 'Portfolio Overview' },
  admin: { open: (page) => signedIn(page, '/trademind/control'), ready: 'Money being used' },
  'admin-alerts': { open: (page) => signedIn(page, '/trademind/alerts'), ready: 'Messages you can switch off' },
}

async function signedIn(page: Page, path: string) {
  await mockApi(page)
  await openPage(page, path)
}

/** Wait for one-off entrance animations (fade-ins) to finish, so contrast is measured at full opacity. */
async function settle(page: Page) {
  await page.waitForFunction(() =>
    document.getAnimations().every((a) => {
      const iterations = a.effect?.getTiming().iterations ?? 1
      return iterations === Infinity || a.playState !== 'running'
    }),
  )
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`axe, ${scheme} colour scheme`, () => {
    test.use({ colorScheme: scheme })

    for (const [key, target] of Object.entries(SCANNED)) {
      test(`${key} has no serious or critical problems`, async ({ page }, info) => {
        await target.open(page)
        // Not exact: a glossary word (e.g. "Market Mode") is a button that also carries hidden screen-reader text.
        await expect(page.getByText(target.ready).first()).toBeVisible()
        await settle(page)

        const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
        const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
        const known = new Set(ALLOWED.filter((a) => a.page === key).map((a) => a.rule))
        const fresh = serious.filter((v) => !known.has(v.id))

        // Known debt that no longer shows up: say so, so the list gets trimmed (not a failure).
        const gone = [...known].filter((rule) => !serious.some((v) => v.id === rule))
        if (gone.length) info.annotations.push({ type: 'allowlist-entry-now-passes', description: `${key}: ${gone.join(', ')}` })

        const report = fresh.map((v) => ({
          rule: v.id,
          impact: v.impact,
          help: v.help,
          where: v.nodes.slice(0, 5).map((n) => n.target.join(' ')),
          detail: v.nodes[0]?.failureSummary,
        }))
        expect(report, `new accessibility problems on ${key} (${scheme})`).toEqual([])
      })
    }
  })
}

test.describe('tap targets at phone width', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('the section menu and page tabs are at least 24 x 24 px (WCAG 2.2 target size)', async ({ page }) => {
    await mockApi(page)
    // Today is one page (no row of tabs); Portfolio and Admin still have theirs.
    for (const path of ['/trademind', '/trademind/positions', '/trademind/control']) {
      await openPage(page, path)
      if (path === '/trademind') await expect(page.getByTestId('subnav')).toHaveCount(0)
      else await expect(page.getByTestId('subnav')).toBeVisible()
      const small = await page
        .locator('nav[aria-label="Sections"] a, [data-testid="subnav"] a, .tm-topbar button, .tm-topbar a')
        .evaluateAll((els) =>
          els
            .map((el) => {
              const r = el.getBoundingClientRect()
              return { text: (el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim(), w: r.width, h: r.height }
            })
            // Hidden at this width (for example the Zerodha chip) means nothing to tap.
            .filter((t) => t.w > 0 && t.h > 0 && (t.w < 24 || t.h < 24)),
        )
      expect(small, `tap targets under 24px on ${path}`).toEqual([])
    }
  })

  test('icon-only buttons in the top bar have a name a screen reader can read', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await expect(page.getByRole('navigation', { name: 'Sections' })).toBeVisible()
    // Today is one page now, so it has no "Today pages" row; a section with several pages still names its row.
    await expect(page.getByRole('navigation', { name: 'Today pages' })).toHaveCount(0)
    // The owner's Log out is the last item of the account menu, reachable from the keyboard.
    const account = page.getByRole('button', { name: 'Your account and settings' })
    await expect(account).toBeVisible()
    await account.focus()
    await page.keyboard.press('Enter')
    const items = page.getByRole('menu').getByRole('menuitem')
    await expect(items.last()).toHaveText('Log out')
    await expect(page.getByRole('menuitem', { name: 'Log out' })).toBeVisible()
    await page.keyboard.press('Escape')
    await openPage(page, '/trademind/positions')
    await expect(page.getByRole('navigation', { name: 'Portfolio pages' })).toBeVisible()
  })

  test('a member keeps a Log out button on the bar', async ({ page }) => {
    await mockApi(page, { role: 'member' })
    await openPage(page, '/trademind')
    await expect(page.getByRole('button', { name: 'Log out' })).toBeVisible()
  })
})

// The top bar for beginners: nothing in it wraps onto a second line on a laptop or a wide screen, it never says
// "LIVE" (which read like real-money trading next to PRACTICE), and a phone gets no sideways scroll. The market text
// is the long one production shows, so the widest real case is measured. GitHub's runner draws text wider than
// Windows does, so the fit check keeps real room to spare instead of passing by a pixel or two.
async function longMarketText(page: Page) {
  await page.route(
    (url) => url.pathname === '/api/v1/market/session',
    (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          state: 'closed', plain: 'Market closed · opens Mon 26 Oct, 9:15 am', trading_day: false,
          opens_at: null, closes_at: null, next_open: '2026-10-26T03:45:00Z', next_close: '2026-10-26T10:00:00Z',
          last_closed_trading_day: '2026-10-23', today: '2026-10-23', recent_closed_trading_days: ['2026-10-23', '2026-10-22'],
          latest_candle_date: '2026-10-23', calendar_warning: null,
        }),
      }),
  )
}

/** Every piece of visible text in the top bar that is drawn on more than one line, with how many lines. */
function wrappedText(page: Page) {
  return page.locator('.tm-topbar').evaluate((bar) => {
    const out: { text: string; lines: number }[] = []
    const walk = document.createTreeWalker(bar, NodeFilter.SHOW_TEXT)
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const text = (n.textContent ?? '').trim()
      if (!text) continue
      const range = document.createRange()
      range.selectNodeContents(n)
      const tops: number[] = []
      for (const r of range.getClientRects()) {
        if (r.width < 1 || r.height < 1) continue
        if (!tops.some((t) => Math.abs(t - r.top) < 4)) tops.push(r.top)
      }
      if (tops.length > 1) out.push({ text, lines: tops.length })
    }
    return out
  })
}

// 1280 = a common laptop, 1880 = the owner's screen. 1152, 1531 and 1861 are the narrowest widths of the other steps
// where the bar shows more or less (see the top-bar note in trademind.css); below 1280px the section menu has a row
// of its own.
for (const width of [1152, 1280, 1531, 1861, 1880]) {
  test.describe(`top bar at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } })

    test('no text wraps, nothing is squeezed out, and the bar never says LIVE', async ({ page }) => {
      await mockApi(page)
      await longMarketText(page)
      await openPage(page, '/trademind')
      const bar = page.locator('.tm-topbar')
      const prices = page.getByTestId('prices-badge')
      await expect(prices).toContainText("Prices from today's close")
      await expect(prices).toHaveAttribute('title', /Market closed · opens Mon 26 Oct, 9:15 am/) // always in the tooltip
      if (width > 1860) await expect(prices).toContainText('Market closed · opens Mon 26 Oct, 9:15 am')
      else if (width > 1530) await expect(prices.locator('.tm-asof-market-short')).toHaveText('Market closed')
      else await expect(page.getByTestId('market-part')).toBeHidden()
      await expect(page.getByTestId('brain-chip')).toHaveText('Brain: up to date')
      await expect(page.getByTestId('stage-chip')).toBeVisible()
      await expect(page.getByRole('button', { name: 'Help' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Your account and settings' })).toBeVisible()
      if (width > 1530 || width < 1280) await expect(bar.getByText('Zerodha connected')).toBeVisible()

      expect(await wrappedText(page), 'top-bar text drawn on two lines').toEqual([])
      await expect(bar).not.toContainText(/\bLIVE\b/i)

      // Each chip and button is one line high (with room for the chip's own padding).
      const tall = await bar
        .locator('.tm-asof, .tm-zchip, .tm-stage-chip, .tm-status-chip, button, nav[aria-label="Sections"] a')
        .evaluateAll((els) =>
          els
            .map((el) => ({ text: (el.textContent ?? '').trim(), h: el.getBoundingClientRect().height, line: parseFloat(getComputedStyle(el).lineHeight) || parseFloat(getComputedStyle(el).fontSize) * 1.5 }))
            .filter((t) => t.h > 0 && t.h > t.line * 1.6 + 16),
        )
      expect(tall, 'top-bar items taller than one line').toEqual([])

      // Room to spare: the five sections are not clipped, and what the bar holds fits with at least 48px left over.
      const room = await bar.evaluate((el) => {
        const nav = el.querySelector<HTMLElement>('nav[aria-label="Sections"]')!
        const gap = parseFloat(getComputedStyle(el).columnGap) || 0
        const pad = parseFloat(getComputedStyle(el).paddingLeft) + parseFloat(getComputedStyle(el).paddingRight)
        const kids = [...el.children] as HTMLElement[]
        // The section menu stretches to fill the bar, so count what its links need, not the width it was given.
        const links = [...nav.children] as HTMLElement[]
        const navNeed = links.reduce((s, a) => s + a.getBoundingClientRect().width, 0) + (parseFloat(getComputedStyle(nav).columnGap) || 0) * (links.length - 1)
        const need = kids.reduce((sum, k) => sum + (k === nav ? navNeed : k.getBoundingClientRect().width), 0)
        return { spare: el.clientWidth - pad - gap * (kids.length - 1) - need, navClipped: nav.scrollWidth - nav.clientWidth }
      })
      expect(room.navClipped, 'section menu cut off').toBeLessThanOrEqual(0)
      expect(await bar.evaluate((el) => el.scrollWidth - el.clientWidth), 'something sticks out of the bar').toBeLessThanOrEqual(0)
      // From 1280px everything sits on one row, with room to spare (below that the section menu has its own row).
      console.log('SPARE', width, Math.round(room.spare))
      if (width >= 1280) expect(room.spare, 'spare width in the top bar').toBeGreaterThanOrEqual(48)
    })
  })
}

test.describe('top bar at phone width', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('no sideways scroll, and the bar never says LIVE', async ({ page }) => {
    await mockApi(page)
    await longMarketText(page)
    for (const path of ['/trademind', '/trademind/positions']) {
      await openPage(page, path)
      await expect(page.getByTestId('prices-badge')).toBeVisible()
      await expect(page.getByTestId('market-part')).toBeHidden() // the market clock part is dropped on a phone
      await expect(page.locator('.tm-topbar')).not.toContainText(/\bLIVE\b/i)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `sideways scroll on ${path}`).toBeLessThanOrEqual(0)
    }
  })
})
