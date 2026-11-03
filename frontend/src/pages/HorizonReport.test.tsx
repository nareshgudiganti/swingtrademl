import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { HorizonReport, HorizonReportRow } from '../api/types'
import { HorizonReportView } from './HorizonReport'
import reportSource from './HorizonReport.tsx?raw'

function row(over: Partial<HorizonReportRow> = {}): HorizonReportRow {
  return {
    key: '15d-mid',
    horizon_days: 15,
    cap_group: 'mid',
    source: 'lanes',
    model: {
      id: 9,
      name: 'sl1_S0M_20230701',
      version: 'v1',
      role: 'fold',
      role_recorded: false,
      role_label: 'Evaluation fold model - not used for daily picks',
      daily_picks_allowed: false,
    },
    qualification: { state: 'not_run', protocol: 'sl-protocol-v1', text: 'Not run: no history test is on file for this lane.' },
    forward: {
      matured_days: 0,
      picks: 0,
      finished: 0,
      net_per_trade: null,
      edge_vs_every_stock: null,
      hit_rate: null,
      nifty: { available: false, mean_return: null, windows: 0, note: 'NIFTY 50 bars are not available here, so no index comparison is shown.' },
    },
    verdict: { state: 'not_enough_days', text: 'Not enough days to judge.', needed_days: 60, rule: 'lane review' },
    ...over,
  }
}

const report = (rows: HorizonReportRow[]): HorizonReport => ({
  note: 'Test records only. Software tests passing does not prove a model works.',
  nifty_note: 'NIFTY 50 comparison is a yardstick.',
  edge_notes: ['Edge note.'],
  fold_model_note: 'Fold models never make daily picks.',
  horizons: rows,
})
const html = (d: HorizonReport | null) => renderToString(<HorizonReportView data={d} />).replace(/<!-- -->/g, '')

describe('Horizon report', () => {
  it('labels a fold model as not used for daily picks and never as a final model', () => {
    const out = html(report([row()]))
    expect(out).toContain('Evaluation fold model - not used for daily picks')
    expect(out).toContain('Fold models are not daily models.')
    expect(out).not.toContain('Final model')
    expect(out).toContain('Not tested yet.')
  })

  it('shows Final model and Qualified only when the server says so', () => {
    const out = html(
      report([
        row({
          model: { id: 1, name: 'sl1_S0M_lane_20261205', version: 'v1', role: 'final', role_recorded: true, role_label: 'Final model', daily_picks_allowed: true },
          qualification: { state: 'qualified', protocol: 'sl-protocol-v1', text: 'Qualified: frozen after a passed history test.' },
        }),
      ]),
    )
    expect(out).toContain('Final model')
    expect(out).toContain('Qualified.')
  })

  it('says "Not enough days to judge" and never turns a missing number into zero', () => {
    const out = html(report([row()]))
    expect(out).toContain('Not enough days to judge.')
    expect(out).toContain('Not measured yet')
    expect(out).not.toContain('+0.00%')
    expect(out).toContain('0 of 60 needed before any reading')
    expect(out).toContain('NIFTY 50 bars are not available here')
  })

  it('shows real numbers as percentages with a sign', () => {
    const out = html(
      report([
        row({
          forward: {
            matured_days: 61,
            picks: 300,
            finished: 280,
            net_per_trade: 0.0123,
            edge_vs_every_stock: -0.004,
            hit_rate: 0.52,
            nifty: { available: true, mean_return: 0.006, windows: 280, note: null },
          },
        }),
      ]),
    )
    expect(out).toContain('+1.23%')
    expect(out).toContain('-0.40%')
    expect(out).toContain('52%')
    expect(out).toContain('+0.60% (280 windows)')
  })

  it('has an empty state and no action buttons or writes', () => {
    expect(html(null)).toContain('No horizon report yet.')
    expect(reportSource).not.toMatch(/\bBuy\b|\bBUY\b|useMutation|api\.(post|patch|put|del)|<button/)
  })
})
