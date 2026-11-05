import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { LanePickRow, LanesResponse, LaneSummary } from '../api/types'
import pageSource from './HorizonPicks.tsx?raw'
import { BANNER, LanePickRowsTable, LanesView } from './HorizonPicks'

function lane(over: Partial<LaneSummary> = {}): LaneSummary {
  return {
    slot_key: 'h15-large',
    horizon_days: 15,
    cap_group: 'large',
    model: { id: 3, name: 'Fifteen-day ranker', version: 'v3' },
    status: 'history_only',
    started_on: null,
    sessions_recorded: 0,
    history: {
      available: true,
      label: "HISTORICAL GATE - SURVIVOR-BIASED UNIVERSE (today's 49 stocks)",
      ranking: { mean_ic: 0.041, lower_bound: 0.012, days: 220 },
      after_cost: { mean_net_return: 0.0123, trades: 340 },
      benchmark_excess: 0.004,
      drawdown: -0.09,
      note: null,
    },
    forward: {
      picks: 0,
      completed: 0,
      open: 0,
      hit_rate: null,
      mean_net_return: null,
      benchmark_excess: null,
      drawdown: null,
      uncertainty: { low: null, high: null },
      sample_warning: null,
      review: { due_after_sessions: 30, sessions_done: 0, state: 'not_due' },
    },
    ...over,
  }
}

const resp = (lanes: LaneSummary[]): LanesResponse => ({ note: 'Test note.', lanes })
const html = (d: LanesResponse | null) =>
  renderToString(<LanesView data={d} selected={null} onSelect={() => {}} />).replace(/<!-- -->/g, '')

describe('Horizon picks lane cards', () => {
  it('keeps history and forward in separate labelled panels', () => {
    const out = html(resp([lane()]))
    expect(out).toContain('History (past data)')
    expect(out).toContain('Forward (live, watch-only)')
    expect(out).toContain('data-panel="history"')
    expect(out).toContain('data-panel="forward"')
    expect(out).toContain("HISTORICAL GATE - SURVIVOR-BIASED UNIVERSE (today&#x27;s 49 stocks)")
    expect(out).toContain('not a portfolio drawdown')
    expect(out).toContain('220 days tested')
    expect(out).toContain('340 trades')
  })

  it('shows missing numbers in words, never as zero', () => {
    const out = html(resp([lane()]))
    expect(out).toContain('Not measured yet')
    expect(out).not.toContain('0.00%')
    const nullHist = html(
      resp([
        lane({
          history: {
            available: true,
            label: null,
            ranking: { mean_ic: null, lower_bound: null, days: null },
            after_cost: { mean_net_return: null, trades: null },
            benchmark_excess: null,
            drawdown: null,
            note: null,
          },
        }),
      ]),
    )
    expect(nullHist).not.toContain('0.00%')
    expect(nullHist).not.toMatch(/>0\.000</)
    const none = html(resp([lane({ history: { ...lane().history, available: false } })]))
    expect(none).toContain('No past-data test is available')
  })

  it('always shows the mid-cap warning and the forward sample warning', () => {
    const mid = html(resp([lane({ slot_key: 'h15-mid', cap_group: 'mid' })]))
    expect(mid).toContain('Mid-cap stocks trade thinner')
    expect(mid).toContain('Mid cap')
    const warn = html(
      resp([lane({ forward: { ...lane().forward, sample_warning: 'Only 3 finished picks: far too few to judge.' } })]),
    )
    expect(warn).toContain('Only 3 finished picks: far too few to judge.')
  })

  it('uses plain-English status words', () => {
    const out = html(
      resp([
        lane({ slot_key: 'a', status: 'history_only' }),
        lane({ slot_key: 'b', status: 'forward_watching' }),
        lane({ slot_key: 'c', status: 'review_due' }),
        lane({ slot_key: 'd', status: 'inconclusive' }),
      ]),
    )
    for (const w of ['History test only', 'Watching live', 'Review due', 'Not enough data yet']) expect(out).toContain(w)
  })

  it('shows the uncertainty range with its sample size', () => {
    const out = html(
      resp([
        lane({
          forward: {
            ...lane().forward,
            completed: 12,
            picks: 14,
            open: 2,
            hit_rate: 0.5,
            mean_net_return: 0.01,
            uncertainty: { low: -0.02, high: 0.04 },
          },
        }),
      ]),
    )
    expect(out).toContain('Could be as low as -2.00% or as high as +4.00% (from 12 finished picks)')
    expect(out).toContain('50% of 12 finished picks')
  })

  it('orders 10-day large, 15-day large, 15-day mid, then others', () => {
    const out = html(
      resp([
        lane({ slot_key: 'x', horizon_days: 5 }),
        lane({ slot_key: 'm', cap_group: 'mid' }),
        lane({ slot_key: 'l15' }),
        lane({ slot_key: 'l10', horizon_days: 10 }),
      ]),
    )
    const a = out.indexOf('<strong>10-day')
    const b = out.indexOf('<strong>15-day · Large')
    const c = out.indexOf('<strong>15-day · Mid')
    const d = out.indexOf('<strong>5-day · Large')
    expect(a).toBeGreaterThan(-1)
    expect(a).toBeLessThan(b)
    expect(b).toBeLessThan(c)
    expect(c).toBeLessThan(d)
  })

  it('says "No lane data yet" for a missing or empty endpoint', () => {
    expect(html(null)).toContain('No lane data yet')
    expect(html(resp([]))).toContain('No lane data yet')
  })

  it('renders lane pick rows', () => {
    const rows: LanePickRow[] = [
      {
        signal_day: '2026-11-03',
        symbol: 'AAA',
        cap_group: 'large',
        rank: 1,
        score: 0.5,
        model_version: 'v3',
        recorded_at: '2026-11-03T10:00:00Z',
        status: 'open',
        net_return: null,
        excess_return: null,
      },
    ]
    const out = renderToString(<LanePickRowsTable rows={rows} />)
    expect(out).toContain('AAA')
    expect(out).toContain('Not yet')
    expect(renderToString(<LanePickRowsTable rows={[]} />)).toContain('No picks recorded yet')
  })

  it('has the fixed banner and no buy or write calls', () => {
    expect(BANNER).toBe('Test picks only. A history pass allows watch-only testing, not trading. Nothing here is advice.')
    expect(pageSource).toContain('{BANNER}')
    expect(pageSource).not.toMatch(/\bBuy\b|\bBUY\b|useMutation|api\.(post|patch|put|del)/)
  })
})
