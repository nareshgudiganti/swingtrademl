import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ScoreMonitor } from './stockParts'

const day = (date: string, score: number) => ({ date, score })

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
