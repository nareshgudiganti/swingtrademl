import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { clockText, errorText, pickState, staleSince, staleText, type QueryLike } from './stateRules'

const base: QueryLike = { data: undefined, error: null, isError: false, isPending: true, fetchStatus: 'fetching', dataUpdatedAt: 0 }

describe('pickState', () => {
  it('is loading while the first fetch runs', () => {
    expect(pickState(base)).toBe('loading')
  })

  it('is offline when react-query paused the first fetch waiting for the network', () => {
    expect(pickState({ ...base, fetchStatus: 'paused' })).toBe('offline')
  })

  it('tells a failed load apart from signed out, not allowed and not found', () => {
    const failed = (error: unknown) => pickState({ ...base, isPending: false, isError: true, error, fetchStatus: 'idle' })
    expect(failed(new TypeError('Failed to fetch'))).toBe('error')
    expect(failed(new ApiError('boom', 500))).toBe('error')
    expect(failed(new ApiError('expired', 401))).toBe('signed-out')
    expect(failed(new ApiError('owner only', 403))).toBe('forbidden')
    expect(failed(new ApiError('none', 404))).toBe('not-found')
  })

  it('is empty only when the data loaded and the caller says it has nothing in it', () => {
    const ok = { ...base, isPending: false, data: [], fetchStatus: 'idle' as const }
    expect(pickState(ok, true)).toBe('empty')
    expect(pickState(ok, false)).toBe('ready')
    // isEmpty is ignored without data: a failure is never shown as "nothing here".
    expect(pickState({ ...base, isPending: false, isError: true, error: new Error('x') }, true)).toBe('error')
  })

  it('keeps showing loaded data when a later refetch fails', () => {
    const q = { ...base, isPending: false, isError: true, error: new TypeError('Failed to fetch'), data: [1], dataUpdatedAt: 1 }
    expect(pickState(q)).toBe('ready')
  })
})

describe('staleSince', () => {
  const loaded = { ...base, isPending: false, data: { x: 1 }, dataUpdatedAt: 1_700_000_000_000, fetchStatus: 'idle' as const }

  it('is null for fresh data or no data', () => {
    expect(staleSince(loaded, true)).toBeNull()
    expect(staleSince(base, false)).toBeNull()
  })

  it('returns when the data loaded if the refetch failed, the browser is offline or the fetch is paused', () => {
    expect(staleSince({ ...loaded, isError: true }, true)).toBe(loaded.dataUpdatedAt)
    expect(staleSince(loaded, false)).toBe(loaded.dataUpdatedAt)
    expect(staleSince({ ...loaded, fetchStatus: 'paused' }, true)).toBe(loaded.dataUpdatedAt)
  })
})

describe('stale notice wording', () => {
  // 2026-10-19 15:42 IST = 10:12 UTC
  const at = Date.UTC(2026, 9, 19, 10, 12)

  it('shows only the time for today (India time)', () => {
    expect(clockText(at, Date.UTC(2026, 9, 19, 12, 0))).toBe('15:42')
  })

  it('adds the date for an earlier day', () => {
    expect(clockText(at, Date.UTC(2026, 9, 20, 4, 0))).toBe('19 Oct, 15:42')
  })

  it('says why the data is old', () => {
    const now = Date.UTC(2026, 9, 19, 11, 0)
    expect(staleText(at, true, now)).toBe("Showing data from 15:42 — can't reach the server right now.")
    expect(staleText(at, false, now)).toBe("Showing data from 15:42 — you're offline.")
  })
})

describe('errorText', () => {
  it('is plain English and names the thing', () => {
    expect(errorText(new TypeError('Failed to fetch'), 'your positions', true)).toMatch(/Could not reach the server to load your positions/)
    expect(errorText(new ApiError('Internal', 503), 'your positions', true)).toMatch(/server had a problem/)
    expect(errorText(new ApiError('x', 500), 'your positions', false)).toMatch(/You're offline/)
  })
})
