// Navigation regression: the TradeMind shell must render, without throwing, at every URL the app serves, for the
// owner and for everyone else, and must put the page in the right section. This is the part of the earlier
// "blank page after moving to a stock" worry that can be checked without a browser: a render that throws leaves a
// blank screen. (Browser clicks are covered by the Phase 1 browser run; see the PR.)
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import TradeMindApp from './TradeMindApp'
import { SECTIONS, findSection } from './menu'

const PATHS = [
  '/trademind',
  ...SECTIONS.flatMap((s) => s.pages.map((p) => p.to)),
  '/trademind/stock/INFY',
  '/trademind/ai/INFY',
  '/trademind/positions/INFY',
  '/trademind/does-not-exist',
]

function render(path: string, ownerConsole: boolean): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TradeMindApp ownerConsole={ownerConsole} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the shell renders at every URL', () => {
  for (const owner of [true, false]) {
    it.each([...new Set(PATHS)])(`${owner ? 'owner' : 'non-owner'}: %s`, (path) => {
      const html = render(path, owner)
      expect(html).toContain('tm-nav') // the menu is there, so the screen is not blank
    })
  }

  it('highlights the section the stock page belongs to', () => {
    const html = render('/trademind/stock/INFY', true)
    const active = findSection('/trademind/stock/INFY')!.id
    expect(html).toMatch(new RegExp(`data-testid="nav-${active}"[^>]*class="[^"]*active|class="[^"]*active[^"]*"[^>]*data-testid="nav-${active}"`))
  })

  it('a non-owner never gets the Admin section in the menu', () => {
    expect(render('/trademind/control', false)).not.toContain('nav-admin')
  })
})
