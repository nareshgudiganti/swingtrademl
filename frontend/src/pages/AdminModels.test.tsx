import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import adminSource from './AdminUsers.tsx?raw'
import pageSource from './AdminModels.tsx?raw'
import { ModelOverviewView, type ModelOverview } from './AdminModels'

const DATA: ModelOverview = {
  horizons: {
    '5': [
      {
        id: 2, name: 'swing_a', version: 'v1', algorithm: 'lightgbm', horizon_days: 5, status: 'ACTIVE',
        approval: { live_approved: true, label: 'Approved: the live scan loads it', role: 'prod', role_recorded: true, approved_at: null, approved_by: 'not recorded' },
        evidence: { trained_at: 'not recorded', training_samples: 1200, accuracy: 'not recorded', precision: 0.5, evaluation_report_link: 'not recorded' },
        last_scored_at: 'never scored', last_shadow_lane_day: null,
        brain_usage: { state: 'unknown', label: 'No Brain or lane record found for this model', last_session: null },
      },
    ],
    '15': [],
  },
  jobs: { worker_alive: false, runs_available: true, rows: [
    { id: 'h05_daily', about: '5-day evaluation lane', scheduled: false, schedule: null, next_run: null, last_started_at: null, last_status: null },
  ] },
  not_recorded: ['Who approved each model'],
}

describe('admin model overview', () => {
  it('is a tab of the admin screen and calls only the read route', () => {
    expect(adminSource).toContain('<AdminModels')
    expect(pageSource).toContain("'/admin/console/models'")
    expect(pageSource).not.toMatch(/method:\s*'(PUT|POST|DELETE|PATCH)'/)
  })
  it('shows identity, approval, unknown fields in words and an empty horizon', () => {
    const html = renderToStaticMarkup(<ModelOverviewView data={DATA} />)
    expect(html).toContain('swing_a')
    expect(html).toContain('5 trading days ahead')
    expect(html).toContain('Approved by: not recorded')
    expect(html).toContain('never scored')
    expect(html).toContain('No approved or frozen 15-day model found.')
    expect(html).toContain('not scheduled (switched off)')
    expect(html).toContain('not reporting')
    expect(html).not.toContain('<button')
  })
})
