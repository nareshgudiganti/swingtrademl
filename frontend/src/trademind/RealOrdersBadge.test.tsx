// tr5: the top bar says whether REAL Zerodha orders from My Holdings are switched on. ON is a red badge, OFF a grey
// one; a failed or missing answer shows nothing (never a wrong "OFF"), and nobody but the real account's owner sees it.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RealOrdersStatus } from '../api/types'
import RealOrdersBadge, { RealOrdersBadgeView } from './RealOrdersBadge'
import TradeMindApp from './TradeMindApp'

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

const status = (enabled: boolean): RealOrdersStatus => ({
  enabled,
  max_order_inr: 10000,
  max_day_inr: 20000,
  spent_today_inr: 0,
  market_open: false,
  market_text: 'Market closed',
  waiting: [],
})

describe('RealOrdersBadgeView', () => {
  it('ON: a red badge that says so', () => {
    const html = renderToString(<RealOrdersBadgeView status={status(true)} />)
    expect(html).toContain('Real orders: ON')
    expect(html).toContain('tm-realorders-on')
    expect(html).toContain('data-on="true"')
    expect(html).toContain('real money')
  })

  it('OFF: a grey badge', () => {
    const html = renderToString(<RealOrdersBadgeView status={status(false)} />)
    expect(html).toContain('Real orders: OFF')
    expect(html).toContain('tm-realorders-off')
    expect(html).not.toContain('tm-realorders-on')
  })

  it('no answer: nothing', () => {
    expect(renderToString(<RealOrdersBadgeView status={undefined} />)).toBe('')
  })
})

describe('RealOrdersBadge (with the server)', () => {
  const draw = (client: QueryClient, enabled = true) =>
    renderToString(
      <QueryClientProvider client={client}>
        <RealOrdersBadge enabled={enabled} />
      </QueryClientProvider>,
    )

  it('draws nothing while the answer is not in', () => {
    expect(draw(new QueryClient())).toBe('')
  })

  it('shows the cached answer (same key as My Holdings)', () => {
    const client = new QueryClient()
    client.setQueryData(['realOrdersStatus'], status(true))
    expect(draw(client)).toContain('Real orders: ON')
  })

  it('a failed request shows nothing, even if an older answer is cached (never a wrong OFF)', () => {
    const client = new QueryClient()
    const q = client.getQueryCache().build(client, { queryKey: ['realOrdersStatus'] })
    q.setState({ status: 'error', error: new Error('refused'), data: status(false), dataUpdatedAt: Date.now() })
    expect(draw(client)).toBe('')
  })

  it('switched off by the caller: nothing', () => {
    const client = new QueryClient()
    client.setQueryData(['realOrdersStatus'], status(true))
    expect(draw(client, false)).toBe('')
  })
})

describe('the top bar badge', () => {
  function render(path: string, opts: { ownerConsole: boolean; realAccount: boolean; enabled?: boolean }): string {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(['status'], { paper_tester_enabled: true, trading_mode: 'paper', broker_authenticated: true })
    client.setQueryData(['plan'], { can_see_real_account: opts.realAccount, unrestricted: opts.ownerConsole, features: [] })
    if (opts.enabled != null) client.setQueryData(['realOrdersStatus'], status(opts.enabled))
    return renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <TradeMindApp ownerConsole={opts.ownerConsole} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }
  const topbar = (html: string) => /<header class="tm-topbar">[\s\S]*?<\/header>/.exec(html)![0]

  it.each(['/trademind', '/trademind/opportunities', '/trademind/portfolio', '/trademind/holdings', '/trademind/risk'])(
    'when ON, the top bar says so: %s',
    (path) => {
      const bar = topbar(render(path, { ownerConsole: true, realAccount: true, enabled: true }))
      expect(bar).toContain('Real orders: ON')
      expect(bar).toContain('tm-realorders-on')
    },
  )

  it('when OFF, the top bar shows the grey badge', () => {
    const bar = topbar(render('/trademind', { ownerConsole: true, realAccount: true, enabled: false }))
    expect(bar).toContain('Real orders: OFF')
    expect(bar).not.toContain('Real orders: ON')
  })

  it('an owner-console account that is not the real account never sees it', () => {
    const bar = topbar(render('/trademind', { ownerConsole: true, realAccount: false, enabled: true }))
    expect(bar).not.toContain('real-orders-badge')
  })

  it('a member (not the owner console) never sees it', () => {
    const bar = topbar(render('/trademind', { ownerConsole: false, realAccount: true, enabled: true }))
    expect(bar).not.toContain('real-orders-badge')
  })
})
