import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { PageState, QueryNotice, QueryState, StaleNotice } from './PageState'
import type { QueryLike } from './stateRules'

const q = (over: Partial<QueryLike> & { refetch?: () => unknown }) => ({
  data: undefined,
  error: null,
  isError: false,
  isPending: false,
  fetchStatus: 'idle' as const,
  dataUpdatedAt: 0,
  refetch: () => undefined,
  ...over,
})

describe('PageState', () => {
  it('shows the reason it was given for an empty state', () => {
    const html = renderToString(<PageState kind="empty" reason="No ideas today: the market is weak." />)
    expect(html).toContain('data-state="empty"')
    expect(html).toContain('No ideas today: the market is weak.')
  })

  it('offers Try again on an error and Sign in when signed out', () => {
    expect(renderToString(<PageState kind="error" what="your positions" onRetry={() => {}} />)).toContain('Try again')
    expect(renderToString(<PageState kind="signed-out" what="your positions" />)).toContain('Sign in')
  })
})

describe('QueryState', () => {
  const render = (query: ReturnType<typeof q>) =>
    renderToString(
      <QueryState q={query as typeof query & { data?: number[] }} what="your positions" isEmpty={(d) => d.length === 0} empty="Nothing held.">
        {(d) => <span>rows:{d.length}</span>}
      </QueryState>,
    )

  it('a failed load is not shown as empty', () => {
    const html = render(q({ isError: true, error: new ApiError('down', 502) }))
    expect(html).toContain('data-state="error"')
    expect(html).not.toContain('Nothing held.')
  })

  it('shows the empty reason only once data loaded with nothing in it', () => {
    expect(render(q({ data: [], dataUpdatedAt: 1 }))).toContain('Nothing held.')
  })

  it('keeps old data on screen with a stale notice when the refetch fails', () => {
    const html = render(q({ data: [1, 2], dataUpdatedAt: Date.UTC(2026, 9, 19, 10, 12), isError: true, error: new TypeError('Failed to fetch') }))
    expect(html).toContain('rows:<!-- -->2')
    expect(html).toContain('data-testid="stale-notice"')
    expect(html).toContain('Showing data from')
  })
})

describe('StaleNotice / QueryNotice', () => {
  it('renders nothing for fresh data', () => {
    expect(renderToString(<StaleNotice q={q({ data: 1, dataUpdatedAt: 5 })} />)).toBe('')
  })

  it('shows loading while there is no data yet', () => {
    expect(renderToString(<QueryNotice q={q({ isPending: true, fetchStatus: 'fetching' })} what="the list" />)).toContain('data-state="loading"')
  })
})

describe('BrainGate keeps a loaded run when the network drops', () => {
  it('shows the page with a stale notice instead of "Could not reach the brain"', async () => {
    const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')
    const { BrainGate } = await import('./ui')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const key = ['brainLatest', 'nightly']
    client.setQueryData(key, { started_at: '2026-10-19T10:00:00Z', banner: { mode: 'NORMAL', headline: null }, decisions: [] })
    client.getQueryCache().find({ queryKey: key })!.setState({ status: 'error', error: new TypeError('Failed to fetch'), fetchStatus: 'idle' })
    const html = renderToString(
      <QueryClientProvider client={client}>
        <BrainGate>
          <span>PAGE-BODY</span>
        </BrainGate>
      </QueryClientProvider>,
    )
    expect(html).toContain('PAGE-BODY')
    expect(html).toContain('data-testid="stale-notice"')
    expect(html).not.toContain('Could not reach the brain')
  })
})
