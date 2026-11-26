// Horizon picks: the two date inputs beside the horizon and size buttons, with their empty and error states, and the
// request that carries them (#322 slice 3a). Read only; nothing here writes.
import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { LaneFilters, PicksTable, datesInvalid, emptyPicksLabel } from '../pages/HorizonPicks'

const noop = () => {}
const html = (from: string, to: string) =>
  renderToString(<LaneFilters from={from} to={to} onFrom={noop} onTo={noop} />).replace(/<!-- -->/g, '')

describe('the date inputs', () => {
  it('are two labelled day inputs, empty by default, with no error', () => {
    const out = html('', '')
    expect(out).toMatch(/<input[^>]*type="date"[^>]*aria-label="From day"/)
    expect(out).toMatch(/<input[^>]*type="date"[^>]*aria-label="To day"/)
    expect(out).not.toContain('role="alert"')
    expect(out).not.toContain('Clear dates')
  })

  it('show the chosen days and offer to clear them', () => {
    const out = html('2026-11-03', '2026-11-05')
    expect(out).toContain('value="2026-11-03"')
    expect(out).toContain('value="2026-11-05"')
    expect(out).toContain('Clear dates')
  })

  it('say plainly when the end is before the start', () => {
    const out = html('2026-11-05', '2026-11-03')
    expect(out).toContain('role="alert"')
    expect(out).toContain('“To” must be on or after “From”')
  })

  it('datesInvalid only fires when both are set and out of order', () => {
    expect(datesInvalid('', '')).toBe(false)
    expect(datesInvalid('2026-11-05', '')).toBe(false)
    expect(datesInvalid('2026-11-04', '2026-11-04')).toBe(false)
    expect(datesInvalid('2026-11-05', '2026-11-04')).toBe(true)
  })
})

describe('the empty state', () => {
  it('keeps the old wording with no dates and names the days when there are some', () => {
    expect(emptyPicksLabel('', '')).toBe('No picks recorded yet for this choice.')
    expect(emptyPicksLabel('2026-11-03', '2026-11-05')).toBe('No picks from 2026-11-03 to 2026-11-05 for this choice.')
    expect(emptyPicksLabel('2026-11-03', '')).toBe('No picks from 2026-11-03 onwards for this choice.')
    expect(emptyPicksLabel('', '2026-11-05')).toBe('No picks up to 2026-11-05 for this choice.')
    const out = renderToString(<PicksTable rows={[]} emptyLabel={emptyPicksLabel('2026-11-03', '2026-11-05')} />)
    expect(out).toContain('No picks from 2026-11-03 to 2026-11-05')
  })
})
