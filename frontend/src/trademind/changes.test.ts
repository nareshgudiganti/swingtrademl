import { describe, expect, it } from 'vitest'

import { changeHeadline, ideaChange, ordinal, rankLine, summarize, type BrainChangeRow, type BrainChangeSide } from './changes'

const side = (over: Partial<BrainChangeSide> = {}): BrainChangeSide => ({
  word: 'WAIT',
  brain_word: 'WAIT',
  overruled_word: null,
  overrule_reason: null,
  reasons: ['Model score 41% is below the buy level 55%.'],
  downgraded_from: null,
  downgrade_reason: null,
  rank: 10,
  rank_of: 100,
  score_kind: 'model',
  ...over,
})
const row = (now: BrainChangeSide | null, before: BrainChangeSide | null, held_now = false): BrainChangeRow => ({
  symbol: 'AAA',
  now,
  before,
  held_now,
})

describe('ideaChange', () => {
  it('a word change wins over everything else', () => {
    const c = ideaChange(row(side({ word: 'TRADE', reasons: ['Strong.'], rank: 2 }), side()))
    expect(c.kind).toBe('word')
    expect(changeHeadline(c)).toBe('Changed from WAIT yesterday to TRADE today.')
    expect(c.placesMoved).toBe(8)
  })

  it('new, dropped and now-held are told apart', () => {
    expect(ideaChange(row(side(), null)).kind).toBe('new')
    expect(ideaChange(row(null, side())).kind).toBe('dropped')
    expect(ideaChange(row(null, side(), true)).kind).toBe('held')
  })

  it('same word, different stored reason → reason changed', () => {
    const risk = 'Good idea, but the risk check said no: Max open positions reached.'
    const c = ideaChange(
      row(
        side({ word: 'WATCH', reasons: [risk], downgraded_from: 'TRADE', downgrade_reason: risk }),
        side({ word: 'WATCH', reasons: ['Its sector ranks 9 of 15 — outside the top 5 for new ideas.'], downgraded_from: 'TRADE', downgrade_reason: 'Its sector ranks 9 of 15 — outside the top 5 for new ideas.' }),
      ),
    )
    expect(c.kind).toBe('reason')
    expect(c.whyBefore[0]!.kind).toBe('weak_sector')
    expect(c.whyNow[0]!.kind).toBe('risk_no_room')
  })

  it('a moving score number is not a reason change; a move in the ranking is reported as places', () => {
    const c = ideaChange(row(side({ reasons: ['Model score 47% is below the buy level 55%.'], rank: 4 }), side({ rank: 20 })))
    expect(c.kind).toBe('rank')
    expect(rankLine(c)).toBe('Moved up 16 places in the ranking (now 4th of 100, was 20th).')
  })

  it('no ranking move across different score kinds (a raw score and a calibrated chance are not one scale)', () => {
    const c = ideaChange(row(side({ score_kind: 'combined', rank: 1 }), side({ rank: 50 })))
    expect(c.placesMoved).toBeNull()
    expect(c.kind).toBe('same')
    expect(rankLine(c)).toBeNull()
  })

  it('never says anything as a percentage', () => {
    const lines = [
      ideaChange(row(side({ rank: 3 }), side({ rank: 9 }))),
      ideaChange(row(side({ word: 'TRADE', reasons: ['x'] }), side())),
      ideaChange(row(side(), null)),
    ].flatMap((c) => [changeHeadline(c), rankLine(c) ?? '', ...c.whyNow.map((w) => w.text), ...c.whyBefore.map((w) => w.text)])
    for (const l of lines) expect(l).not.toContain('%')
  })
})

describe('summarize and ordinal', () => {
  it('groups the changes for the Today page', () => {
    const s = summarize([
      ideaChange(row(side({ word: 'TRADE', reasons: ['x'] }), side())),
      ideaChange(row(side(), null)),
      ideaChange(row(null, side())),
      ideaChange(row(side({ rank: 40 }), side({ rank: 10 }))),
      ideaChange(row(side({ rank: 9 }), side({ rank: 10 }))),
    ])
    expect(s.wordChanged).toHaveLength(1)
    expect(s.newToday).toHaveLength(1)
    expect(s.dropped).toHaveLength(1)
    expect(s.bigMoves).toHaveLength(1)
    expect(s.bigMoves[0]!.placesMoved).toBe(-30)
  })

  it('ordinals', () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111].map(ordinal)).toEqual([
      '1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '101st', '111th',
    ])
  })
})
