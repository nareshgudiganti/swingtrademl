// ob15: the Observatory's minor display fixes from the Phase 1A review.
import { describe, expect, it } from 'vitest'

import type { ObsModuleRow, ObsRunDetail } from '../api/types'
import {
  countOrUnknown, headlineText, notObservedText, problemCauses, runDuration, timeIst,
} from './observatoryText'

const flags = (on: Partial<ObsModuleRow['flags']>) =>
  ({
    expected: false, executed: false, valid_output: false, used: false, shadow: false, switched_off: false,
    failed: false, not_observed: false, not_applicable: false, not_installed_then: false, unknown: false,
    unknown_module: false, duplicate: false, conflicting: false, ...on,
  }) as ObsModuleRow['flags']

const detail = (over: Partial<ObsRunDetail>): ObsRunDetail =>
  ({ headline: 'completed', modules: [], counts: {}, step_fallbacks: [], ...over }) as unknown as ObsRunDetail

describe('run duration', () => {
  it('an unfinished run says so instead of 0 s', () => {
    expect(runDuration({ status: 'running', ms: 0, finished_at: null })).toBe('not finished yet')
    expect(runDuration({ status: 'queued', ms: 0, finished_at: null })).toBe('not finished yet')
  })
  it('a finished run shows seconds', () => {
    expect(runDuration({ status: 'done', ms: 41000, finished_at: '2026-10-15T10:21:00Z' })).toBe('41 s')
  })
  it('a finished run with no time stored does not claim 0 s', () => {
    expect(runDuration({ status: 'failed', ms: 0, finished_at: '2026-10-15T10:21:00Z' })).toBe('time taken not recorded')
  })
})

describe('run times', () => {
  it('converts the stored UTC time to India time', () => {
    expect(timeIst('2026-10-15T10:20:00+00:00')).toBe('15:50 IST')
    expect(timeIst('2026-10-15T18:45:00Z')).toBe('00:15 IST')
  })
  it('a missing time says so', () => {
    expect(timeIst(null)).toBe('time not recorded')
  })
})

describe('run headline', () => {
  it('a run with no module list is not called Completed', () => {
    expect(headlineText('completed_unchecked')).not.toBe('Completed')
    expect(headlineText('completed_unchecked')).toMatch(/no module list/)
  })
  it('keeps the existing words', () => {
    expect(headlineText('completed')).toBe('Completed')
    expect(headlineText('degraded')).toBe('Completed with problems')
  })
})

describe('Completed with problems names its cause', () => {
  it('lists failed, missing and conflicting modules and fallbacks', () => {
    const r = detail({
      headline: 'degraded',
      modules: [
        { module_id: 'M07', flags: flags({ failed: true }) },
        { module_id: 'M06', flags: flags({ not_observed: true }) },
      ] as ObsModuleRow[],
      step_fallbacks: [{ step: 'decide', reason: 'x' }],
    })
    const causes = problemCauses(r).join(' | ')
    expect(causes).toMatch(/1 module\(s\) failed: M07/)
    expect(causes).toMatch(/not seen in the step log: M06/)
    expect(causes).toMatch(/safe default: decide/)
  })
  it('says nothing for a clean run', () => {
    expect(problemCauses(detail({ headline: 'completed' }))).toEqual([])
  })
})

describe('not observed count', () => {
  it('an old run without a module list does not read "0 not observed"', () => {
    const t = notObservedText(detail({ counts: { unknown: 5, not_observed: 0 } }))
    expect(t).not.toMatch(/^0 not observed/)
    expect(t).toMatch(/cannot tell/)
  })
  it('a run with a module list shows the count', () => {
    expect(notObservedText(detail({ counts: { unknown: 0, not_observed: 2 } }))).toBe('2 not observed (inferred)')
  })
})

describe('counts the server could not read', () => {
  it('never prints "null"', () => {
    expect(countOrUnknown(null, 'day(s) in another stage')).not.toMatch(/null/)
    expect(countOrUnknown(3, 'day(s) in another stage')).toBe('3 day(s) in another stage')
  })
})
