import { describe, expect, it } from 'vitest'

import { countFailed, errorWords, formatDuration, formatIST, formatNext, jobState, type JobRow } from './jobs'

const base: JobRow = {
  id: 'daily_ingest',
  name: 'Daily candles',
  about: '',
  registered: true,
  schedule: 'Weekdays at 15:40',
  next_run: null,
  last_started_at: null,
  last_finished_at: null,
  last_duration_s: null,
  last_status: null,
  last_error_kind: null,
  running_since: null,
  last_missed_at: null,
  last_skipped_at: null,
}

describe('formatIST', () => {
  it('shows India time whatever the input zone', () => {
    expect(formatIST('2026-10-19T10:10:00Z')).toBe('19 Oct, 15:40')
    expect(formatIST('2026-10-19T15:40:00+05:30')).toBe('19 Oct, 15:40')
    expect(formatIST('2026-10-19T18:30:00Z')).toBe('20 Oct, 00:00')
  })
  it('shows a dash for nothing or nonsense', () => {
    expect(formatIST(null)).toBe('—')
    expect(formatIST('not a date')).toBe('—')
  })
})

describe('formatDuration', () => {
  it.each([
    [null, '—'],
    [0.2, 'under 1 s'],
    [4.24, '4.2 s'],
    [42, '42 s'],
    [60, '1 min'],
    [192, '3 min 12 s'],
    [3900, '1 h 5 min'],
    [7200, '2 h'],
  ])('%s -> %s', (s, text) => {
    expect(formatDuration(s as number | null)).toBe(text)
  })
})

describe('jobState', () => {
  it('ok, failed, running, not run yet', () => {
    expect(jobState({ ...base, last_status: 'ok', last_started_at: '2026-10-19T10:10:00Z' }).label).toBe('OK')
    const failed = jobState({ ...base, last_status: 'failed', last_error_kind: 'OperationalError' })
    expect(failed).toMatchObject({ label: 'Failed', tone: 'red', detail: 'database problem' })
    expect(jobState({ ...base, running_since: '2026-10-19T10:10:00Z' }).label).toBe('Running')
    expect(jobState(base).label).toBe('Not run yet')
  })
  it('a miss after the last run shows Missed; an older miss does not', () => {
    const run = { ...base, last_status: 'ok' as const, last_started_at: '2026-10-19T10:10:00Z' }
    expect(jobState({ ...run, last_missed_at: '2026-10-20T10:10:00Z' }).label).toBe('Missed')
    expect(jobState({ ...run, last_missed_at: '2026-10-18T10:10:00Z' }).label).toBe('OK')
    expect(jobState({ ...base, last_missed_at: '2026-10-18T10:10:00Z' }).label).toBe('Missed')
  })
  it('a skipped run after the last run shows Skipped', () => {
    const run = { ...base, last_status: 'ok' as const, last_started_at: '2026-10-19T10:10:00Z' }
    expect(jobState({ ...run, last_skipped_at: '2026-10-19T10:11:00Z' }).label).toBe('Skipped')
  })
  it('counts failed jobs', () => {
    expect(countFailed([base, { ...base, last_status: 'failed' }, { ...base, last_status: 'ok' }])).toBe(1)
  })
})

describe('errorWords and formatNext', () => {
  it('names known error kinds plainly and keeps unknown ones', () => {
    expect(errorWords('TokenException')).toBe('Zerodha login expired')
    expect(errorWords('KeyError')).toBe('KeyError')
    expect(errorWords(null)).toBe('unknown error')
  })
  it('says "due now" once the next run time has passed', () => {
    const now = Date.parse('2026-10-19T10:15:00Z')
    expect(formatNext('2026-10-19T10:10:00Z', now)).toBe('due now')
    expect(formatNext('2026-10-19T10:20:00Z', now)).toBe('19 Oct, 15:50')
    expect(formatNext(null, now)).toBe('—')
  })
})
