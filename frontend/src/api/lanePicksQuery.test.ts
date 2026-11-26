// The Horizon picks request carries the two days beside horizon and cap (#322 slice 3a).
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from './client'

describe('the request', () => {
  afterEach(() => vi.unstubAllGlobals())

  async function urlFor(call: () => Promise<unknown>): Promise<string> {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ rows: [], lanes: [], summary: {}, note: '' })))
    vi.stubGlobal('fetch', fetchMock)
    await call()
    return String((fetchMock.mock.calls[0] as unknown[])[0])
  }

  it('sends from and to only when they are set, beside horizon and cap', async () => {
    expect(await urlFor(() => api.lanePicks())).toMatch(/\/research\/lane-picks$/)
    const url = await urlFor(() => api.lanePicks(5, 'mid', '2026-11-03', '2026-11-05'))
    expect(url).toContain('horizon=5')
    expect(url).toContain('cap=mid')
    expect(url).toContain('from=2026-11-03')
    expect(url).toContain('to=2026-11-05')
    const only = await urlFor(() => api.lanePicks(undefined, undefined, '2026-11-03'))
    expect(only).toContain('from=2026-11-03')
    expect(only).not.toContain('to=')
  })
})
