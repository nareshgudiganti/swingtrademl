// The top bar for beginners: the brain chip never says "LIVE" (it read like real-money trading next to PRACTICE),
// the owner's Log out is the last item of the account menu, the market clock and the prices' age are one chip,
// and Today has no row of tabs under the bar.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import latestRun from '../../e2e/fixtures/brain-latest-run.json'
import { AccountMenuList, logOut } from './AccountMenu'
import TradeMindApp from './TradeMindApp'
import { ADMIN_SECTION } from './menu'
import { STATUS_CHIP, statusChip, type BrainStatus } from './statusChip'

const store = new Map<string, string>()
beforeEach(() => {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
})
afterEach(() => {
  vi.unstubAllGlobals()
})

const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')

describe('the brain chip', () => {
  const ALL: BrainStatus[] = ['live', 'no-run', 'off', 'loading', 'error']

  it.each([
    ['live', 'Brain: up to date'],
    ['no-run', 'Brain: no run yet'],
    ['off', 'Brain is off'],
    ['loading', 'Brain: checking…'],
    ['error', "Brain: can't connect"],
  ] as const)('%s reads "%s"', (status, label) => {
    expect(STATUS_CHIP[status].label).toBe(label)
  })

  it('never says live, in any state, in its label', () => {
    for (const s of ALL) expect(statusChip(s).label).not.toMatch(/\blive\b/i)
    expect(statusChip('live', { refreshFailing: true }).label).not.toMatch(/\blive\b/i)
  })

  it('is the only green state when the latest run is on screen; every other state keeps the amber warning look', () => {
    expect(statusChip('live').ok).toBe(true)
    for (const s of ALL.filter((x) => x !== 'live')) expect(statusChip(s).ok).toBe(false)
  })

  it('names the run time and says it is not about real-money trading', () => {
    const chip = statusChip('live', { runAt: '23 Oct, 18:05' })
    expect(chip.title).toContain('from 23 Oct, 18:05')
    expect(chip.title).toContain('does not mean real-money trading is on')
  })

  it("says so when a run is on screen but a newer one can't be checked for", () => {
    const chip = statusChip('live', { runAt: '23 Oct, 18:05', refreshFailing: true })
    expect(chip.label).toBe("Brain: can't refresh")
    expect(chip.ok).toBe(false)
    expect(chip.title).toContain('23 Oct, 18:05')
  })
})

describe('the account menu', () => {
  const draw = (el: ReactElement) => renderToString(<MemoryRouter>{el}</MemoryRouter>)

  it('lists the Admin pages, then Log out as the last item (a menu item button)', () => {
    const html = draw(<AccountMenuList pages={ADMIN_SECTION.pages} />)
    const items = [...html.matchAll(/<(a|button)[^>]*role="menuitem"[^>]*>([^<]*)</g)].map((m) => [m[1], m[2]])
    expect(items.map((i) => i[1])).toEqual([...ADMIN_SECTION.pages.map((p) => p.label), 'Log out'])
    expect(items.at(-1)).toEqual(['button', 'Log out'])
    expect(html).toMatch(/<button type="button" role="menuitem"/) // a real button: Tab reaches it, Enter/Space press it
  })

  it('Log out in the menu calls the log-out action', () => {
    const onLogOut = vi.fn()
    const tree = AccountMenuList({ pages: ADMIN_SECTION.pages, onLogOut })
    const find = (n: ReactNode): ReactElement<{ onClick?: () => void; children?: ReactNode }> | undefined => {
      if (Array.isArray(n)) return n.map(find).find(Boolean)
      if (!isValidElement<{ onClick?: () => void; children?: ReactNode }>(n)) return undefined
      if (n.type === 'button') return n
      return find(n.props.children)
    }
    find(tree)!.props.onClick!()
    expect(onLogOut).toHaveBeenCalledTimes(1)
  })

  it('log out forgets the saved sign-in and goes back to the start, as the old bar button did', () => {
    store.set('stml.token', 'x')
    const assign = vi.fn()
    vi.stubGlobal('window', { location: { assign } })
    logOut()
    expect(store.has('stml.token')).toBe(false)
    expect(assign).toHaveBeenCalledWith('/')
  })
})

describe('the top bar', () => {
  function render(path: string, ownerConsole: boolean, latest: unknown = undefined): string {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(['status'], { paper_tester_enabled: true, trading_mode: 'paper', broker_authenticated: true })
    if (latest) client.setQueryData(['brainLatest', 'nightly'], latest)
    client.setQueryData(['marketSession'], {
      state: 'closed', plain: 'Market closed · opens Mon 26 Oct, 9:15 am', trading_day: false, opens_at: null, closes_at: null,
      next_open: '2026-10-26T09:15:00+05:30', next_close: '2026-10-26T15:30:00+05:30',
      last_closed_trading_day: '2026-10-23', today: '2026-10-23',
      recent_closed_trading_days: ['2026-10-23', '2026-10-22'], calendar_warning: null,
      latest_candle_date: '2026-10-23',
    })
    client.setQueryData(['plan'], { can_see_real_account: ownerConsole, unrestricted: ownerConsole, features: [] })
    return renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <TradeMindApp ownerConsole={ownerConsole} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }
  const topbar = (html: string) => /<header class="tm-topbar">[\s\S]*?<\/header>/.exec(html)![0]

  it('shows the market clock and the prices age as one chip, with both explanations in its tooltip', () => {
    const bar = topbar(render('/trademind', true))
    const chips = [...bar.matchAll(/data-testid="prices-badge"/g)]
    expect(chips).toHaveLength(1)
    const start = bar.lastIndexOf('<span', bar.indexOf('data-testid="prices-badge"'))
    const chip = bar.slice(start, bar.indexOf('tm-asof-short', start))
    expect(text(chip)).toContain('Market closed · opens Mon 26 Oct, 9:15 am')
    expect(text(chip)).toContain("Prices from today's close")
    const title = /title="([^"]*)"/.exec(chip)![1]!.replace(/&#x27;/g, "'")
    expect(title).toContain('Indian stock market (NSE) hours') // the old market chip's tooltip
    expect(title).toContain('Up to date: these are the latest closing prices') // the old prices badge's tooltip (pricesAge detail)
    expect(bar).not.toContain('tm-market-chip')
  })

  it('never shows the word LIVE, for the owner or anyone else', () => {
    for (const owner of [true, false]) {
      const bar = topbar(render('/trademind', owner, latestRun))
      expect(text(bar)).not.toMatch(/\blive\b/i)
      expect(text(bar)).toContain('Brain: up to date')
    }
  })

  it("the owner's bar has no Log out button (it is in the account menu); anyone else keeps one on the bar", () => {
    expect(text(topbar(render('/trademind', true)))).not.toContain('Log out')
    expect(topbar(render('/trademind', false))).toMatch(/<button[^>]*class="tm-logout"[^>]*>Log out<\/button>/)
  })

  it.each(['/trademind', '/trademind/dashboard'])('Today has no row of tabs under the bar: %s', (path) => {
    for (const owner of [true, false]) {
      const html = render(path, owner)
      expect(html).not.toContain('data-testid="subnav"')
      expect(html).not.toContain('Swing Picks</a>')
    }
  })

  it('other sections still have their row of tabs', () => {
    expect(render('/trademind/positions', true)).toContain('data-testid="subnav"')
  })
})
