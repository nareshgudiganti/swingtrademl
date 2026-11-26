// #240 chart states on main's current code: missing-session markers on GlowArea, and the Candles edge cases.
// recharts cannot size itself without a browser, so the recharts parts are replaced by plain stand-ins that keep their props:
// this proves ui.tsx asks recharts for a marker per missing day and prints the note, not recharts' own drawing.
import { renderToString } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: unknown }) => <div>{children as never}</div>
  const Nothing = () => null
  return {
    ResponsiveContainer: Pass,
    AreaChart: Pass,
    Area: Nothing,
    CartesianGrid: Nothing,
    Tooltip: Nothing,
    XAxis: Nothing,
    YAxis: Nothing,
    ReferenceLine: (p: { x?: string; 'data-testid'?: string }) => <i data-testid={p['data-testid']} data-x={p.x} />,
  }
})

import { MISSING_DAY_NOTE } from './chartSessions'
import { Candles, GlowArea } from './ui'

const bar = (i: number) => ({ t: `${i + 1} Dec`, o: 100 + i, h: 102 + i, l: 98 + i, c: 101 + i, vol: 1000 + i })
const count = (html: string, re: RegExp) => (html.match(re) ?? []).length

describe('GlowArea marks a missing trading day', () => {
  it('emits one missing-day reference line per missing point and shows the note', () => {
    const data = [
      { t: '11-19', v: 100 },
      { t: '11-20', v: null, missing: true },
      { t: '11-23', v: 102 },
    ]
    const html = renderToString(<GlowArea data={data} />)
    expect(count(html, /data-testid="missing-day"/g)).toBe(1)
    expect(html).toContain('data-x="11-20"')
    expect(html).toContain('data-testid="missing-day-note"')
    expect(html).toContain(MISSING_DAY_NOTE)
  })

  it('draws no marker and no note when no day is missing', () => {
    const html = renderToString(<GlowArea data={[{ t: '11-19', v: 100 }, { t: '11-20', v: 101 }]} />)
    expect(html).not.toContain('missing-day')
    expect(html).not.toContain(MISSING_DAY_NOTE)
  })
})

describe('Candles edge cases', () => {
  it('zero volume on every candle: valid candle, no volume bar, no NaN', () => {
    const html = renderToString(<Candles bars={[{ t: '1 Dec', o: 100, h: 101, l: 99, c: 100, vol: 0 }]} height={300} />)
    expect(html).not.toMatch(/NaN|Infinity/)
    expect(html).toContain('<svg')
    expect(count(html, /opacity="0\.35"/g)).toBe(1) // the volume rect is still emitted, with zero height
    expect(html).toMatch(/opacity="0\.35"/)
    const volRect = html.match(/<rect[^>]*opacity="0\.35"[^>]*>/)![0]
    expect(volRect).toMatch(/height="0"/)
  })

  it('a quiet day beside a busy day: the busy bar keeps height, the quiet one has none', () => {
    const quiet = { t: '1 Dec', o: 100, h: 101, l: 99, c: 100, vol: 0 }
    const html = renderToString(<Candles bars={[quiet, bar(1)]} height={300} />)
    expect(html).not.toMatch(/NaN|Infinity/)
    const heights = [...html.matchAll(/<rect[^>]*opacity="0\.35"[^>]*>/g)].map((m) => /height="([^"]*)"/.exec(m[0])![1])
    expect(heights).toHaveLength(2)
    expect(heights[0]).toBe('0')
    expect(Number(heights[1])).toBeGreaterThan(0)
  })

  // DECISION PENDING (owner): #509 drew "No price history to draw yet." for empty bars. #520 does not, because the owner
  // has not decided. This test documents what happens today so the decision is visible: empty bars render nothing at all.
  // If the owner chooses to add the message, change this test with that change.
  it('documents current behaviour: empty bars render nothing (no message, no svg, no NaN)', () => {
    const html = renderToString(<Candles bars={[]} height={300} />)
    expect(html).toBe('')
    expect(html).not.toContain('No price history to draw yet.')
  })
})
