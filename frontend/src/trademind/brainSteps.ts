// The stock page's "How the brain thought about it" (new look): the brain's eight steps for one stock, built ONLY
// from what the brain stored on its latest run. Pure functions, no hooks.
//
// Honesty rules (owner decision 5, 2026-10-25): until the brain saves a reason at every step (after the trial ends
// on 7 Nov), a stock's record holds the reasons up to the step that stopped it. So:
//   * the step that stopped it is marked "Stopped here", with the stored reason in plain words;
//   * facts stored for the whole run (data check, market mode, the score) are shown for every stock;
//   * any other step after the stop says "Not recorded", never a guessed pass;
//   * the score is a ranking, never a chance of profit; step 8 (learning) only happens after an idea ends.

import type { BrainDecision, BrainRun } from '../api/types'
import { finalWord, stockSituations } from './live'
import { rankText, scorePoints, scoreRank } from './scoreText'
import { MARKET_LABEL, MARKET_PLAIN } from './vocab'
import { whyNotTrade, type WhyItem, type WhyKind } from './whyNotTrade'

export type StepState = 'ok' | 'warn' | 'stop' | 'word' | 'none' | 'later'
export type BrainStep = { n: number; title: string; line: string; state: StepState; tag: string }

export const STEP_TITLES = [
  'Look at the data',
  'Read the market',
  'Recognise the situation',
  'Remember similar times',
  'Form an opinion',
  'Safety check',
  'Decide',
  'Learn from results',
] as const

/** The step whose stored reason holds the idea back (1-7), from the first "why not TRADE" reason. */
const STOP_STEP: Record<Exclude<WhyKind, 'owner_overrule' | 'other'>, number> = {
  no_price: 1,
  data_not_reliable: 1,
  careful_market_downtrend: 2,
  exchange_watch_list: 3,
  results_or_event: 3,
  weak_sector: 3,
  no_setup: 3,
  similar_cases_lost: 4,
  below_buy_level: 5,
  no_clear_signal: 5,
  weak_signals: 5,
  risk_no_room: 6,
  risk_not_approved: 6,
  buys_paused: 6,
  bad_plan: 7,
}

export const NOT_RECORDED = 'Not recorded for this stock yet: the brain saves every step from 7 Nov.'

const WORD_PLAIN: Record<string, string> = {
  TRADE: 'Buy it, with the usual plan (+8% target, −4% stop, out within 15 trading days).',
  WATCH: 'Not a TRADE today. Keep an eye on it.',
  WAIT: 'Nothing to do today.',
  AVOID: 'Stay away for now.',
  HOLD: 'Keep it: the plan is working.',
  MONITOR: 'Keep it, but watch it closely.',
  REDUCE: 'Sell some.',
  EXIT: 'Sell it all.',
}

/** Where the brain stopped this idea, and why: null for a TRADE or when nothing stored says why. */
export function stopOf(d: BrainDecision): { step: number; why: WhyItem } | null {
  const brain = whyNotTrade(d).filter((w) => w.kind !== 'owner_overrule')
  const first = brain[0]
  if (!first) return null
  const kind = first.kind
  return { step: kind === 'other' || kind === 'owner_overrule' ? 7 : STOP_STEP[kind], why: first }
}

export function brainSteps(d: BrainDecision, run: BrainRun): BrainStep[] {
  const stop = stopOf(d)
  const stopAt = stop?.step ?? 99
  const after = (n: number) => n > stopAt
  const word = finalWord(d)
  const steps: BrainStep[] = []
  const push = (n: number, line: string, state: StepState, tag: string) =>
    steps.push({ n, title: STEP_TITLES[n - 1]!, line, state, tag })
  const stopped = (n: number) => push(n, stop!.why.text, 'stop', 'Stopped here')

  // 1 · data
  if (stopAt === 1) stopped(1)
  else {
    const q = run.quality.overall
    const stale = run.quality.stale.map((s) => s.toUpperCase()).includes(d.symbol.toUpperCase())
    if (stale) push(1, 'Prices for this stock were old on this run.', 'warn', 'Old prices')
    else if (q && q.fresh && q.issues.length === 0) push(1, 'Prices were fresh and passed the data check.', 'ok', 'OK')
    else if (q) push(1, `The data check flagged: ${q.issues[0] ?? 'prices not fresh'}.`, 'warn', 'Check')
    else push(1, 'The data check result was not stored.', 'none', 'Not recorded')
  }

  // 2 · market (stored for the whole run)
  if (stopAt === 2) stopped(2)
  else {
    const mode = run.banner.mode
    if (mode) push(2, MARKET_PLAIN[mode] ?? mode, mode === 'NORMAL' ? 'ok' : 'warn', (MARKET_LABEL[mode] ?? mode).toUpperCase())
    else push(2, 'The market mode was not stored.', 'none', 'Not recorded')
  }

  // 3 · situation
  if (stopAt === 3) stopped(3)
  else {
    const sit = stockSituations(run, d.symbol).find((s) => s.label && s.label !== 'unlabelled')
    if (sit) push(3, sit.evidence[0] ? `${sit.label}: ${sit.evidence[0]}` : sit.label, sit.suggest_defensive ? 'warn' : 'ok', sit.is_unknown ? 'NEW' : 'NAMED')
    else if (after(3)) push(3, NOT_RECORDED, 'none', 'Not recorded')
    else push(3, 'No special situation was named for this stock.', 'ok', 'Nothing unusual')
  }

  // 4 · similar past cases (measured track record, never a promise)
  if (stopAt === 4) stopped(4)
  else {
    const tr = d.honest_score?.track_record
    if (tr?.enough_evidence && tr.n != null && tr.hit_rate != null) {
      const hits = Math.round(tr.hit_rate * tr.n)
      push(4, `${tr.n} similar past cases: ${hits} reached the target, ${tr.n - hits} did not. Past results, not a promise.`, 'ok', 'MEASURED')
    } else if (d.evidence_text) push(4, d.evidence_text, 'ok', 'NOTED')
    else push(4, after(4) ? NOT_RECORDED : 'Not enough similar past cases to measure.', 'none', 'Not recorded')
  }

  // 5 · opinion (the score is a ranking among today's ideas)
  if (stopAt === 5) stopped(5)
  else {
    const scores = run.decisions.filter((x) => x.kind === 'idea').map((x) => x.confidence)
    const rank = d.kind === 'idea' ? scoreRank(d.confidence, scores) : null
    const pts = scorePoints(d.confidence)
    if (pts != null) push(5, `Score ${pts}${rank ? ` — ${rankText(rank).toLowerCase()}` : ''}. A ranking, not a chance of profit.`, 'ok', rank ? `RANK #${rank.rank}` : 'SCORED')
    else push(5, 'No score was stored for this stock.', 'none', 'Not recorded')
  }

  // 6 · safety check
  if (stopAt === 6) stopped(6)
  else if (word === 'TRADE') push(6, 'Passed: the account’s safety limits allow it.', 'ok', 'PASSED')
  else push(6, NOT_RECORDED, 'none', 'Not recorded')

  // 7 · decide
  if (stopAt === 7) push(7, `${stop!.why.text} ${WORD_PLAIN[word] ?? ''}`.trim(), 'word', word)
  else push(7, WORD_PLAIN[word] ?? word, 'word', word)

  // 8 · learn
  push(8, 'Happens after an idea finishes. You will see it in History.', 'later', 'LATER')
  return steps
}
