// #238: one 5-day large-cap idea across Today, Stock Detail and AI Analysis (verification; nothing here changes the app).
// The backend side (the same stored decision behind all three) is in backend/tests/test_verify_238_5d_ideas_screens.py.
// Here: the screens turn that one decision into the same words, and none of them keeps a formula of its own.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../api/types'
import { effectiveWord } from './beginner/IdeaCard'
import { shownWord } from './live'
import { scoreLabel, scoreLabelLong, scorePoints } from './scoreText'
import { ideaCounts } from './today/TodayIdeas'

const here = path.dirname(fileURLToPath(import.meta.url))
const read = (file: string) => fs.readFileSync(path.join(here, file), 'utf8')

const IDEA = {
  id: 1,
  run_id: 'r1',
  symbol: 'ZZLARGECAP',
  kind: 'idea',
  word: 'TRADE',
  confidence: 0.84,
  horizon_days: 15,
  entry_low: 100,
  entry_high: 101,
  target: 108,
  stop: 96,
  reasons: ['The market is calm and the stock is in an up-trend.'],
} as unknown as BrainDecision

describe('one idea reads the same on Today, Stock Detail and AI Analysis', () => {
  it('the word and the score text come from the shared helpers', () => {
    expect(shownWord(IDEA)).toBe('TRADE')
    expect(scorePoints(IDEA.confidence)).toBe(84)
    // on a list that holds the day's scores the place in the ranking; alone, the plain number
    expect(scoreLabel(IDEA.confidence, [0.84, 0.7, 0.6])).toBe('Rank 1 of 3 today')
    expect(scoreLabel(IDEA.confidence)).toBe('Model score 84')
    expect(scoreLabelLong(IDEA.confidence)).toContain('Model score 84')
  })

  it('an owner overrule is shown by every screen through the same word helper', () => {
    expect(shownWord({ ...IDEA, overruled_word: 'WAIT' } as BrainDecision)).toBe('WAIT')
  })

  it('Stock Detail, AI Analysis and the ideas table take their word from one shared helper', () => {
    // #486: wordFor(d, owner) gives the owner the stored word (as Today does) and everyone else shownWord
    for (const file of ['IdeasTable.tsx', 'pages/StockDetail.tsx', 'pages/AIDecision.tsx', 'pages/StockAnalysis.tsx']) {
      expect(read(file), `${file} shows a word`).toMatch(/useWordFor|wordFor|shownWord/)
    }
  })

  it('no screen rounds the score its own way', () => {
    for (const file of ['today/TodayIdeas.tsx', 'IdeasTable.tsx', 'pages/StockDetail.tsx', 'pages/AIDecision.tsx', 'pages/StockAnalysis.tsx']) {
      expect(read(file), `${file} keeps its own score formula`).not.toMatch(/confidence\s*\*\s*100/)
    }
  })

  // GAP: three different "word" helpers. Stock Detail, AI Analysis and the ideas table use shownWord (the stock verdict when
  // only the test portfolio's room held the idea back); Today's counts use finalWord and Today's idea cards use effectiveWord
  // (the stored word). For the owner, an idea restored to TRADE reads TRADE on its stock page and WATCH on Today.
  const RESTORED = { ...IDEA, word: 'WATCH', stock_verdict: 'TRADE', stock_verdict_restored: true } as unknown as BrainDecision

  it("control: Today's counts and cards file the restored idea under the stored word WATCH (the cause of the gaps below)", () => {
    const counts = ideaCounts({ decisions: [RESTORED] } as unknown as BrainRun)
    expect([counts.WATCH, counts.TRADE]).toEqual([1, 0])
    expect(effectiveWord(RESTORED as never)).toBe('WATCH')
    expect(shownWord(RESTORED)).toBe('TRADE') // while the stock page shows the stock verdict
  })

  it.fails("GAP: Today's idea counts agree with the word Stock Detail shows when the account's room alone held the idea back", () => {
    expect(shownWord(RESTORED)).toBe('TRADE')
    const run = { decisions: [RESTORED] } as unknown as BrainRun
    expect(ideaCounts(run).TRADE).toBe(1)
  })

  it.fails("GAP: Today's idea card word is the word Stock Detail shows when the account's room alone held the idea back", () => {
    expect(effectiveWord(RESTORED as never)).toBe(shownWord(RESTORED))
  })

  it('the day-by-day score line rounds exactly like the headline score for every score from 0 to 1', () => {
    // stockParts.tsx and HeldRead.tsx round the trail with Math.round(x * 100); the headline uses scorePoints.
    for (let i = 0; i <= 1000; i++) {
      const x = i / 1000
      expect(Math.round(x * 100), `score ${x}`).toBe(scorePoints(x))
    }
  })

  it('Today, Stock Detail, AI Analysis and the stock analysis page all read the idea from the latest run', () => {
    for (const file of ['pages/TodayNew.tsx', 'pages/StockDetail.tsx', 'pages/AIDecision.tsx', 'pages/StockAnalysis.tsx']) {
      expect(read(file), `${file} reads the latest run`).toContain('useLatestRun')
    }
  })

  it('the stock pages call the score a 5-day model score and the plan is worded separately', () => {
    expect(read('stockParts.tsx')).toContain('5-day model score')
    expect(read('scoreVsPlan.ts')).toMatch(/separate rule/)
  })
})
