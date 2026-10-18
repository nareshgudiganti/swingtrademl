import { describe, expect, it } from 'vitest'

import type { BrainHealth } from '../api/types'
import { noTradeReason, runFailedNote } from './emptyReasons'

const health = (last: Partial<NonNullable<BrainHealth['last_run']>> | null): BrainHealth => ({
  last_run: last
    ? { run_id: 'r2', kind: 'nightly', started_at: '2026-10-19T12:00:00Z', status: 'failed', ms: 10, error: 'boom', ...last }
    : null,
  last_nightly_ok: null,
  failed_runs_7d: 1,
  data: { score: null, fresh: null, issues: [] },
  stale_count: 0,
})

describe('noTradeReason', () => {
  it('says nothing when there are TRADE ideas', () => {
    expect(noTradeReason({ mode: 'NO_NEW_TRADES', headline: null }, 10, 1)).toBeNull()
  })

  it('gives the banner as the reason: No new trades and Careful read differently', () => {
    const stop = noTradeReason({ mode: 'NO_NEW_TRADES', headline: 'Market fell hard.' }, 10, 0)!
    const careful = noTradeReason({ mode: 'DEFENSIVE', headline: null }, 10, 0)!
    expect(stop).toMatch(/No new trades/)
    expect(stop).toMatch(/Market fell hard\.$/)
    expect(careful).toMatch(/Careful/)
    expect(careful).not.toEqual(stop)
  })

  it('never invents a market reason on a normal day', () => {
    const normal = noTradeReason({ mode: 'NORMAL', headline: null }, 10, 0)!
    expect(normal).not.toMatch(/weak|shaky|market/i)
    expect(noTradeReason({ mode: null, headline: null }, 0, 0)).toMatch(/no stocks to look at/)
  })
})

describe('runFailedNote', () => {
  it('flags a failed nightly run newer than the one on screen', () => {
    expect(runFailedNote('2026-10-18T12:00:00Z', health({}))).toMatch(/did not finish/)
  })

  it('stays quiet when the newest run finished, is older, or is not a nightly run', () => {
    expect(runFailedNote('2026-10-18T12:00:00Z', health({ status: 'done' }))).toBeNull()
    expect(runFailedNote('2026-10-20T12:00:00Z', health({}))).toBeNull()
    expect(runFailedNote('2026-10-18T12:00:00Z', health({ kind: 'why' }))).toBeNull()
    expect(runFailedNote('2026-10-18T12:00:00Z', health(null))).toBeNull()
    expect(runFailedNote('2026-10-18T12:00:00Z', undefined)).toBeNull()
  })
})
