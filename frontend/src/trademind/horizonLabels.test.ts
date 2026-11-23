// #326, wording only: every statement of the Brain's 15-day numbers (+8% target, 15 trading days) names the window
// it speaks about, so it can never be read as a statement about the 5-day plan. The numbers themselves are
// unchanged: each row below only adds the label. A 15-day statement that is true for Brain positions stays 15.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { modelLabel } from '../lib/format'

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '..', '..', '..')

// Who a label speaks about. 'brain': positions and ideas that belong to the Brain's own 15-day trial.
// 'app': a screen or rule that applies to every book (bot, Brain, testers, Groww Tracker), so it must never say
// "the Brain". A label about the Brain that is shown on an app-wide screen is the mistake this guards against.
type About = 'brain' | 'app'
type Label = { file: string; now: string; was?: string; about: About }

// Every label this change touched: the file, the text it now has, and the unlabelled text it replaced.
const LABELS: Label[] = [
  {
    file: 'frontend/src/auth/PublicSite.tsx',
    now: '−4% stop, +8% target in our 15-day test portfolio',
    was: "in the Brain's 15-day trial",
    about: 'app',
  },
  {
    file: 'frontend/src/auth/PublicSite.tsx',
    now: 'In our 15-day test portfolio: −4% stop, +8% target, out within 15 trading days.',
    was: "In the Brain's 15-day trial:",
    about: 'app',
  },
  {
    file: 'frontend/src/trademind/Tour.tsx',
    now: 'This is the plan the Brain follows in its 15-day trial.</p>',
    // Codex round 1 P2: the claim that a stock's page names its own window is not true yet, so it is gone.
    was: 'names the window it uses',
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/Tour.tsx',
    now: `title: "The Brain's plan for a trade"`,
    was: "title: 'The plan for every trade'",
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/Tour.tsx',
    now: 'in the 15-day trial, out within 15 trading days, about three weeks.',
    was: '<Term k="horizon">Time limit</Term>: out within 15 trading days',
    about: 'brain',
  },
  {
    file: 'frontend/src/lib/format.ts',
    // Codex round 1 P2: the model name does not prove the horizon (training takes it separately), so the label
    // claims no number and no window, only what a barrier model asks.
    now: '(trial model: estimates the chance of target before stop)',
    was: 'hits its target before its stop',
    about: 'app',
  },
  {
    file: 'frontend/src/components/HoldingTracker.tsx',
    now: `"Past the Brain's 15-day plan"`,
    was: "'Past 15 days'",
    about: 'brain',
  },
  {
    file: 'frontend/src/components/HoldingTracker.tsx',
    now: "of up to 15 (the Brain's 15-day plan)",
    was: 'of up to 15`',
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/pages/PaperPositions.tsx',
    // Codex round 1 P2: a tooltip is invisible on touch, so the scale is named in the visible header.
    now: 'Progress (−4% to +8%, app 15-day scale)</SortTh>',
    was: 'Progress (−4% to +8%)</SortTh>',
    about: 'app',
  },
  {
    file: 'frontend/src/trademind/pages/PaperPositions.tsx',
    now: "the app's 15-day plan scale",
    was: "between the Brain's 15-day plan stop and target",
    about: 'app',
  },
  {
    file: 'frontend/src/trademind/pages/GrowwTracker.tsx',
    now: "The app's 15-day plan, used here as a yardstick for each stock: +8% target",
    was: "The Brain's 15-day plan for each stock",
    about: 'app',
  },
  {
    file: 'frontend/src/trademind/pages/GrowwTracker.tsx',
    now: 'Nothing is bought or sold.',
    about: 'app',
  },
  {
    file: 'frontend/src/trademind/pages/IdeaReports.tsx',
    now: "target: 'Hit +8% first (15-day trial)'",
    was: "target: 'Hit +8% first',",
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/pages/IdeaReports.tsx',
    now: "the 15-day trial's +8% / −4% results unlock",
    was: '              the +8% / −4% results unlock',
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/pages/IdeaReports.tsx',
    now: '15-day trial: hit +8% first',
    was: 'aria-label={`Hit +8% first',
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/pages/IdeaReports.tsx',
    now: 'Hit +8% first (15-day trial) ·',
    was: 'Hit +8% first · {res.target}',
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/today/answerRules.ts',
    now: "every trade in the Brain's 15-day trial has a −4% stop, a +8% target and a 15-trading-day limit.",
    was: "'Safety net on: every trade has a −4% stop",
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/honest.tsx',
    now: "The Brain's 15-day trial estimate: chance of +8% before −4% within 15 trading days",
    was: '`Estimated chance of +8% before −4% within 15 trading days',
    about: 'brain',
  },
  // ---- the last unlabelled plan statements (round 2): each names the window and that it is the 15-day plan ----
  {
    file: 'frontend/src/trademind/brainSteps.ts',
    now: "Buy it, with the Brain's 15-day plan (+8% target, −4% stop, out within 15 trading days).",
    was: 'Buy it, with the usual plan',
    about: 'brain',
  },
  {
    file: 'frontend/src/pages/Brain.tsx',
    now: '(+8%, 15-day plan)`,',
    was: '(+8%)`,',
    about: 'brain',
  },
  {
    file: 'frontend/src/pages/Brain.tsx',
    now: 'Target (+8%, 15-day plan)</div>',
    was: 'Target (+8%)</div>',
    about: 'brain',
  },
  {
    file: 'frontend/src/trademind/pages/positionLevels.ts',
    now: "It hit the +8% target of the app's 15-day plan. Consider booking profit.",
    was: "'It hit the +8% target. Consider booking profit.'",
    about: 'app',
  },
  {
    file: 'frontend/src/trademind/pages/positionLevels.ts',
    now: 'from your +8% target (15-day plan). Consider booking profit at the target.',
    was: 'from your +8% target. Consider booking profit at the target.',
    about: 'app',
  },
  {
    file: 'frontend/src/trademind/pages/PositionParts.tsx',
    now: '+8%{big && <em>Target · 15-day plan</em>}',
    was: '+8%{big && <em>Target</em>}',
    about: 'app',
  },
  {
    file: 'frontend/src/trademind/pages/PositionParts.tsx',
    now: '(+8%, 15-day plan)</dd>',
    was: '(+8%)</dd>',
    about: 'app',
  },
  {
    file: 'backend/src/swing_trade_ml/services/holdings_health.py',
    now: "Trades in the app's {plan_days}-day plan are meant to be finished within {plan_days} ",
    was: "Trades in the Brain's {plan_days}-day plan",
    about: 'app',
  },
  {
    file: 'backend/src/swing_trade_ml/services/holdings_health.py',
    // the kept sentence: the 30-calendar-day safety sell (it spans two source lines)
    now: 'sell happens after 30 calendar days, which is about the same length',
    about: 'app',
  },
  {
    file: 'backend/src/swing_trade_ml/services/holdings_health.py',
    now: "(the app's {PLAN_TRADING_DAYS}-day plan)",
    was: "(the Brain's {PLAN_TRADING_DAYS}-day plan)",
    about: 'app',
  },
  {
    file: 'backend/src/swing_trade_ml/services/holdings_health.py',
    now: "settings.ML_PREDICTION_HORIZON_DAYS (the app's 15-day plan)",
    was: "(the Brain's 15-day plan)",
    about: 'app',
  },
]

const read = (file: string): string => fs.readFileSync(path.join(repo, file), 'utf8').replace(/\r\n/g, '\n')

describe('every changed label names its horizon (#326)', () => {
  it.each(LABELS.map((l) => [l.file, l.now, l.was ?? '']))('%s: "%s"', (file, now, was) => {
    const text = read(file as string)
    expect(text, 'the labelled wording is there').toContain(now)
    if (was) expect(text, 'the unlabelled wording is gone').not.toContain(was as string)
  })
})

// No model is proven, so a model label may say what the model ESTIMATES, never that it succeeds.
describe('a model label never states success (#326)', () => {
  const SUCCESS = /\b(hits?|reach(es)?|beats?|works?|succeed[s]?|wins?|delivers?|guarantee[sd]?)\b/i
  it.each(['swing_classifier_barrier:v3', 'ml_swing_midcap_barrier:v1', 'ml_swing_smallcap_barrier'])(
    '%s',
    (name) => {
      const label = modelLabel(name)
      expect(label).not.toMatch(SUCCESS)
      expect(label).toContain('estimates the chance of target before stop')
    },
  )
  it('the model label rows in the label list say the same', () => {
    const rows = LABELS.filter((l) => l.file === 'frontend/src/lib/format.ts')
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) expect(row.now).not.toMatch(SUCCESS)
  })
})

// An app-wide label must not say "the Brain": look at the whole line it sits on, not only the label text.
describe('app-wide labels never say "the Brain" (#326)', () => {
  const appWide = LABELS.filter((l) => l.about === 'app')
  it.each(appWide.map((l) => [l.file, l.now]))('%s: "%s"', (file, now) => {
    const lines = read(file as string).split('\n')
    const first = (now as string).split('\n')[0] ?? ''
    const hits = lines.filter((line) => line.includes(first))
    expect(hits.length, 'the label is on a line of the file').toBeGreaterThan(0)
    for (const line of hits) expect(line).not.toMatch(/the Brain/i)
  })
  it('every label says who it speaks about', () => {
    expect(LABELS.every((l) => l.about === 'brain' || l.about === 'app')).toBe(true)
  })
})

// A statement of the Brain's numbers must carry its window on the same line. The 5-day plan's own numbers
// (+2% target, 5 days) are untouched and not matched here.
const NUMBERS = /\+8 ?%|15[ -]trading[ -]days?|15-trading-day/
const WINDOW = /15-day (trial|plan|test portfolio)|15 days, trial|5-day plan|Brain's/i

describe('no unlabelled +8% or "15 trading days" remains in the files this change touched', () => {
  const files = [...new Set(LABELS.map((l) => l.file))]
  it.each(files)('%s', (file) => {
    const bare = read(file)
      .split('\n')
      .map((line, i) => ({ line, n: i + 1 }))
      .filter(({ line }) => !/^\s*(\/\/|\*|\/\*)/.test(line)) // a comment is not shown to anyone
      .filter(({ line }) => NUMBERS.test(line) && !WINDOW.test(line))
    expect(bare.map(({ n, line }) => `${n}: ${line.trim()}`)).toEqual([])
  })

  it('the numbers themselves are unchanged (each labelled line still carries its figure)', () => {
    expect(read('frontend/src/trademind/today/answerRules.ts')).toContain('a +8% target and a 15-trading-day limit')
    expect(read('frontend/src/trademind/Tour.tsx')).toContain('out within 15 trading days, about three weeks')
    expect(read('frontend/src/trademind/pages/GrowwTracker.tsx')).toContain('+8% target, −4% stop, sell')
    expect(read('frontend/src/trademind/honest.tsx')).toContain('+8% before −4% within 15 trading days')
  })
})
