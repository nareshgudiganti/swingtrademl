import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../api/types'
import { ScoreChart } from './pages/StockAnalysis'
import { brainModelOf, latestRun, modelKey, modelLabel, sameModel, ScoreMonitor, scoreToday } from './stockParts'

// KEC on 2026-11-10, as stored: the daily trail comes from the small-cap model, the brain's number from model 2.
const SMALL = 'swing_classifier_smallcap:v1'
const kecTrail = [
  { date: '2026-11-03', score: 0.9342, model: SMALL },
  { date: '2026-11-04', score: 0.8565, model: SMALL },
  { date: '2026-11-05', score: 0.8579, model: SMALL },
  { date: '2026-11-06', score: 0.8227, model: SMALL },
  { date: '2026-11-09', score: 0.7986, model: SMALL },
  { date: '2026-11-10', score: 0.8093, model: SMALL },
]
// A held stock: its stored lines name no model.
const kecBrain = {
  symbol: 'KEC',
  kind: 'holding',
  confidence: 0.7653723415976902,
  reasons: ['The market is careful and this stock is falling — watch it closely.', 'On track: ₹334, +3.7% since buying.'],
} as unknown as BrainDecision
const run = { started_at: '2026-11-10T10:20:00Z' } as BrainRun
const pts = (v: number) => Math.round(v * 100)
const dayNumbers = (html: string) => [...html.matchAll(/<strong>(\d+)<\/strong>/g)].map((m) => Number(m[1]))

describe('model identity helpers', () => {
  it('treats "name:version" and "name version" as one model, and a missing name as no match', () => {
    expect(modelKey('swing_classifier:v2')).toBe(modelKey('swing_classifier v2'))
    expect(sameModel('swing_classifier:v2', 'swing_classifier v2')).toBe(true)
    expect(sameModel('swing_classifier:v2', 'swing_classifier_smallcap:v1')).toBe(false)
    expect(sameModel(null, null)).toBe(false)
    expect(modelLabel(null)).toBe('model not recorded')
    expect(modelLabel('swing_classifier_smallcap:v1')).toBe('swing_classifier_smallcap v1')
  })

  it('reads the brain model from an explanation only as display text', () => {
    const named = { reasons: ['The active model (swing_classifier v2) scores this stock 63%; its buy level is 60%.'] } as BrainDecision
    expect(brainModelOf(named)).toBe('swing_classifier v2')
    expect(brainModelOf(kecBrain)).toBeNull()
  })
})

describe('latestRun: only the latest unbroken run of one known model', () => {
  const a = (date: string, score: number) => ({ date, score, model: 'm:v1' })
  const b = (date: string, score: number) => ({ date, score, model: 'm:v2' })

  it('is the whole trail when one model gave every day', () => {
    expect(latestRun(kecTrail)).toHaveLength(6)
  })

  it('starts after the last model change', () => {
    const t = [a('2026-10-01', 0.5), a('2026-10-02', 0.52), b('2026-10-05', 0.8), b('2026-10-06', 0.82)]
    expect(latestRun(t).map((x) => x.date)).toEqual(['2026-10-05', '2026-10-06'])
  })

  it('treats a switch back as a new run, and a day with no model as a break', () => {
    const t = [a('2026-10-01', 0.5), b('2026-10-02', 0.8), a('2026-10-05', 0.6), a('2026-10-06', 0.62)]
    expect(latestRun(t).map((x) => x.date)).toEqual(['2026-10-05', '2026-10-06'])
    const gap = [a('2026-10-01', 0.5), { date: '2026-10-02', score: 0.6, model: null }, a('2026-10-05', 0.6)]
    expect(latestRun(gap).map((x) => x.date)).toEqual(['2026-10-05'])
  })

  it('has no comparable run when the latest day records no model', () => {
    expect(latestRun([a('2026-10-01', 0.5), { date: '2026-10-02', score: 0.6 }])).toEqual([])
    expect(latestRun([])).toEqual([])
  })
})

describe('KEC: the trail and the brain score stay apart', () => {
  const today = scoreToday(kecBrain, run)!

  it('the trail keeps its model on every day and ends 80 → 81', () => {
    expect(today.date).toBe('2026-11-10')
    const days = latestRun(kecTrail)
    expect(days.slice(-2).map((t) => pts(t.score))).toEqual([80, 81])
    expect(days.every((t) => t.model === SMALL)).toBe(true)
  })

  it('renders the trail ending 80 → 81 and the brain’s 77 on its own, never as a day', () => {
    const html = renderToStaticMarkup(<ScoreMonitor trail={kecTrail} today={today} />)
    expect(dayNumbers(html).slice(-2)).toEqual([80, 81])
    expect(dayNumbers(html)).not.toContain(77)
    expect(html).toContain('Brain’s score today: 77')
    expect(html).toContain('model not recorded')
    expect(html).toContain('swing_classifier_smallcap v1') // the daily line names its own model
    expect(html).toContain('not a point on the daily line')
    expect(html).not.toContain('data-model-break')
    expect(html).not.toMatch(/\d\s*%/) // a score never carries a % sign
  })

  it('even a brain line that names the SAME model is not joined onto the trail', () => {
    const named = {
      ...kecBrain,
      reasons: ['The active model (swing_classifier_smallcap v1) scores this stock 77%; its buy level is 60%.'],
    } as unknown as BrainDecision
    const html = renderToStaticMarkup(<ScoreMonitor trail={kecTrail} today={scoreToday(named, run)!} />)
    expect(dayNumbers(html)).toEqual([93, 86, 86, 82, 80, 81].slice(-7))
    expect(html).toContain('Brain’s score today: 77')
  })

  it('the score chart draws the trail only: no brain number, and no buy-level line', () => {
    const html = renderToStaticMarkup(<ScoreChart trail={kecTrail} />)
    expect(html).not.toContain('Buy level')
    expect(html).not.toContain('sp-chart-line')
    expect(html).toContain('swing_classifier_smallcap v1')
    expect(html).toContain('<em>81</em>')
    expect(html).not.toContain('<em>77</em>')
  })
})

describe('regression: a model switch inside the trail', () => {
  const A = 'swing_classifier_smallcap:v1'
  const B = 'swing_classifier_smallcap:v2'
  // 55 → 80 is the new model reading higher, not the stock rising 25 points.
  const switched = [
    { date: '2026-11-03', score: 0.5, model: A },
    { date: '2026-11-04', score: 0.52, model: A },
    { date: '2026-11-05', score: 0.55, model: A },
    { date: '2026-11-06', score: 0.8, model: B },
    { date: '2026-11-09', score: 0.82, model: B },
  ]

  it('the monitor marks the break and counts no move across it', () => {
    const html = renderToStaticMarkup(<ScoreMonitor trail={switched} />)
    expect(html.match(/data-testid="score-monitor-break"/g)).toHaveLength(1)
    expect(html).toContain('model changed: swing_classifier_smallcap v2')
    expect(html).not.toContain('▲ 25') // 55 → 80 would be a 25-point "rise"
    expect(html).toContain('▲ 2') // 80 → 82, inside the new model
    expect(html).toContain('▲ 3') // 52 → 55, inside the old model
    expect(html).toContain('the line is broken')
  })

  it('the score chart shows only the new model’s days and says where it cut', () => {
    const html = renderToStaticMarkup(<ScoreChart trail={switched} />)
    expect(html.match(/<i /g)).toHaveLength(2) // two bars: 06 and 09 Nov
    expect(html).toContain('Days up to 2026-11-05 came from a different model')
    expect(html).toContain('<em>82</em>')
  })

  it('with a single day on the new model there is no trend to draw', () => {
    const html = renderToStaticMarkup(<ScoreChart trail={switched.slice(0, 4)} />)
    expect(html).toContain('Not enough daily scores from one model yet')
    expect(html).not.toContain('<em>')
  })
})
