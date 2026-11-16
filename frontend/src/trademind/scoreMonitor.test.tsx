import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { pickTrail, ScoreMonitor } from './stockParts'

const day = (date: string, score: number) => ({ date, score, model: 'swing_classifier:v2' })

describe('ScoreMonitor', () => {
  it('lists the last 7 days with the score, the move and a mark after a gap', () => {
    const trail = [
      day('2026-10-15', 0.7), day('2026-10-16', 0.72), day('2026-10-19', 0.75), day('2026-10-20', 0.8),
      day('2026-10-21', 0.78), day('2026-10-22', 0.78), day('2026-10-23', 0.74), day('2026-10-28', 0.86),
    ]
    const html = renderToStaticMarkup(<ScoreMonitor trail={trail} level="70" />)
    expect(html.match(/data-testid="score-monitor-day"/g)).toHaveLength(7) // oldest of the 8 is dropped
    expect(html).not.toContain('15 Oct')
    expect(html).toContain('<strong>86</strong>')
    expect(html).toContain('▲ 12') // 74 → 86
    expect(html).toContain('▼ 4') // 78 → 74
    expect(html).toContain('same')
    expect(html).toContain('after a gap') // 23 Oct → 28 Oct
    expect(html).toContain('Buy level: 70')
  })

  it('says so when there are no daily scores yet, instead of an empty box', () => {
    const html = renderToStaticMarkup(<ScoreMonitor trail={[]} />)
    expect(html).toContain('No daily scores saved for this stock yet')
    expect(html).not.toContain('score-monitor-day')
  })
})

// DEEPAKNTR, 16 Nov 2026: the headline said 82 (brain, large-company model) while the line beside it ended on 45
// (mid-size model's daily check). The line must be the brain's own, ending on the headline number.
describe('ScoreMonitor with the brain’s own line', () => {
  const brain = (date: string, score: number) => ({ date, score, model: 'swing_classifier v2' })
  const mid = { date: '2026-11-16', score: 0.45, model: 'swing_classifier_midcap:v2' }

  it('ends on the headline number and names the other model separately, never as a day', () => {
    const trail = [brain('2026-11-12', 0.74), brain('2026-11-13', 0.79), brain('2026-11-16', 0.82)]
    const html = renderToStaticMarkup(
      <ScoreMonitor trail={trail} today={brain('2026-11-16', 0.82)} source="brain" other={mid} />,
    )
    expect(html.match(/data-testid="score-monitor-day"/g)).toHaveLength(3)
    expect(html).toContain('<strong>82</strong>')
    expect(html).not.toContain('<strong>45</strong>')
    expect(html).toContain('The last one is the same number as the headline')
    expect(html).not.toContain('score-monitor-brain') // no second "brain's score today" sentence
    expect(html).toContain('data-testid="score-monitor-other"')
    expect(html).toContain('mid-size companies')
    expect(html).toContain('It gave 45 on')
  })

  it('does not name the other model when it is the same model as the line', () => {
    const html = renderToStaticMarkup(
      <ScoreMonitor
        trail={[brain('2026-11-16', 0.82)]}
        source="brain"
        other={{ date: '2026-11-16', score: 0.8, model: 'swing_classifier:v2' }}
      />,
    )
    expect(html).not.toContain('score-monitor-other')
  })

  it('pickTrail uses the brain’s line when it has days, else the daily check’s', () => {
    const b = [brain('2026-11-16', 0.82)]
    expect(pickTrail(b, [mid])).toEqual({ trail: b, trailSource: 'brain', dailyTrail: [mid] })
    expect(pickTrail([], [mid])).toEqual({ trail: [mid], trailSource: 'daily', dailyTrail: [mid] })
  })
})
