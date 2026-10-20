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
  'sign-in': {
    open: async (page) => {
      await mockApi(page, { signedIn: false })
      await page.goto('/')
    },
    ready: 'Sign in to your account.',
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
    for (const path of ['/trademind', '/trademind/positions', '/trademind/control']) {
      await openPage(page, path)
      await expect(page.getByTestId('subnav')).toBeVisible()
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
    await expect(page.getByRole('button', { name: 'Your account and settings' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Log out' })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Sections' })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Today pages' })).toBeVisible()
  })
})
