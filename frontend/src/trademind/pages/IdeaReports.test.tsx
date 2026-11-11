// Portfolio > Reports draws what the server sent: days done / left and scores always, results only when unsealed.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { IdeaReport, IdeaReportRow } from '../../api/types'
import IdeaReports from './IdeaReports'

const row = (over: Partial<IdeaReportRow> = {}): IdeaReportRow => ({
  symbol: 'CYIENT', word: 'WATCH', entry_day: '2026-11-06', entry_score: 72, score_band: '70-80', latest_score: 76,
  latest_word: 'WATCH', still_this_word: true, horizon_days: 15, days_done: 4, days_left: 11, regime: 'DEFENSIVE',
  status: 'tracking', sealed: true, outcome: null, return_pct: null, best_pct: null, worst_pct: null, result_days: null,
  ...over,
})

const report = (rows: IdeaReportRow[], sealed: boolean): IdeaReport => ({
  from: '2026-09-12', to: '2026-11-11', sessions: 20, last_session: '2026-11-10', rows,
  summary: {
    ideas: rows.length, tracking: rows.filter((r) => r.status === 'tracking').length, due: 0,
    finished: rows.filter((r) => r.status === 'finished').length, still_this_word: rows.length, sealed_ideas: sealed ? rows.length : 0,
    results: { ideas: sealed ? 0 : 1, target: sealed ? 0 : 1, stop: 0, timeout: 0, avg_return_pct: sealed ? null : 8 },
  },
  seal: { active: sealed, from: '2026-10-14', text: 'Sealed', outcome_filter_hides_sealed: false },
  options: { words: ['TRADE', 'WATCH'], bands: ['90+', '80-90', '70-80', '60-70', 'below 60'], horizons: [15], regimes: ['DEFENSIVE'], outcomes: ['target', 'stop', 'timeout', 'open'] },
})

function draw(data: IdeaReport) {
  const qc = new QueryClient()
  qc.setQueryData(['ideaReport', ['WATCH'], [], [], [], [], false], data)
  // React puts <!-- --> between text pieces; drop them so assertions read like the page.
  return renderToString(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <IdeaReports />
      </MemoryRouter>
    </QueryClientProvider>,
  ).replace(/<!-- -->/g, '')
}

describe('IdeaReports', () => {
  it('shows days done and left and the score then and now, but no result, while sealed', () => {
    const html = draw(report([row()], true))
    expect(html).toContain('CYIENT')
    expect(html).toContain('4 done')
    expect(html).toContain('11 left')
    expect(html).toContain('72')
    expect(html).toContain('76')
    expect(html).toContain('data-testid="report-sealed"')
    expect(html).toContain('Hidden')
    expect(html).not.toContain('+8.0%')
  })

  it('shows the result and the +8% / −4% counts once unsealed', () => {
    const html = draw(
      report([row({ sealed: false, status: 'finished', outcome: 'target', return_pct: 8, result_days: 6 })], false),
    )
    expect(html).toContain('+8.0%')
    expect(html).toContain('Hit +8% first')
    expect(html).not.toContain('data-testid="report-sealed"')
  })

  it('lets the owner pick the score ranges', () => {
    const html = draw(report([row()], true))
    for (const b of ['90+', '80-90', '70-80', '60-70']) expect(html).toContain(b)
  })
})
