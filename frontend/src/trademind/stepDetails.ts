// The full reasoning behind each step of the chain, as short bullets: what the brain stored, in plain words.
// Display only. Built ONLY from the brain's stored run and decision, never guessed, and never an account figure
// (no room, no size, no limit): a customer decides how much to invest himself.

import type { BrainDecision, BrainRun } from '../api/types'
import { shownWord, stockSituations } from './live'
import { rankText, scorePoints, scoreRank } from './scoreText'
import { MARKET_PLAIN } from './vocab'

export type BulletTone = 'ok' | 'warn' | 'bad' | 'info'
export type Bullet = { tone: BulletTone; text: string }
export type StepLink = { label: string; to: string }
export type StepDetail = { bullets: Bullet[]; links: StepLink[] }

/** Stored reason lines that quote the account (the risk check's own words): never shown. */
const ACCOUNT_LINE = /risk check|risk gate|minimum position|room for only|half size|account|position slot|cash|drawdown/i

const FALLING = /down-?trend|falling|downtrend/i

function cleanReasons(d: BrainDecision): string[] {
  return (d.reasons ?? []).filter((r) => typeof r === 'string' && r.trim() !== '' && !ACCOUNT_LINE.test(r))
}

function sectorLine(d: BrainDecision): Bullet | null {
  const line = cleanReasons(d).find((r) => /^Sector:/i.test(r.trim()))
  if (!line) return null
  const text = line.replace(/^Sector:\s*/i, 'Sector: ').trim()
  return { tone: /lagging|weaker|weak/i.test(text) ? 'bad' : 'ok', text }
}

function trendBullet(d: BrainDecision, run: BrainRun): Bullet | null {
  const sits = stockSituations(run, d.symbol).filter((s) => s.label && s.label !== 'unlabelled')
  const s = sits[0]
  if (!s) return null
  const label = s.label.replace(/_/g, ' ')
  if (FALLING.test(label)) return { tone: 'bad', text: `The stock is in a down-trend (${label}).` }
  return { tone: s.suggest_defensive ? 'warn' : 'ok', text: `The brain read this stock as: ${label}.` }
}

/** The bullets for one chain step (`n` is the step number used by brainSteps: 1-5, 7). */
export function stepDetail(d: BrainDecision, run: BrainRun, n: number): StepDetail {
  const sym = d.symbol
  const bullets: Bullet[] = []
  const links: StepLink[] = []
  const word = shownWord(d)
  const scores = run.decisions.filter((x) => x.kind === 'idea').map((x) => x.confidence)
  const rank = d.kind === 'idea' ? scoreRank(d.confidence, scores) : null
  const pts = scorePoints(d.confidence)

  if (n === 1) {
    const q = run.quality.overall
    const stale = run.quality.stale.map((s) => s.toUpperCase()).includes(sym.toUpperCase())
    if (stale) bullets.push({ tone: 'warn', text: 'Prices for this stock were old on this run.' })
    else if (q && q.fresh && q.issues.length === 0) bullets.push({ tone: 'ok', text: 'Prices were fresh and complete.' })
    else if (q) bullets.push({ tone: 'warn', text: `The data check flagged: ${q.issues[0] ?? 'prices not fresh'}.` })
    else bullets.push({ tone: 'info', text: 'The data check result was not stored.' })
    for (const i of (q?.issues ?? []).slice(1, 3)) bullets.push({ tone: 'warn', text: i })
  } else if (n === 2) {
    const mode = run.banner.mode
    if (mode) {
      bullets.push({ tone: mode === 'NORMAL' ? 'ok' : 'warn', text: MARKET_PLAIN[mode] ?? mode })
      if (mode !== 'NORMAL') bullets.push({ tone: 'info', text: 'A careful market means new buys need extra proof before the brain says BUY.' })
      if (run.banner.headline) bullets.push({ tone: 'info', text: run.banner.headline })
    } else bullets.push({ tone: 'info', text: 'The market mode was not stored.' })
    links.push({ label: 'Open the Market page', to: '/trademind/market' })
  } else if (n === 3) {
    const sits = stockSituations(run, sym).filter((s) => s.label && s.label !== 'unlabelled')
    for (const s of sits) {
      bullets.push({ tone: FALLING.test(s.label) ? 'bad' : s.suggest_defensive ? 'warn' : 'ok', text: `Situation: ${s.label.replace(/_/g, ' ')}.` })
      for (const e of s.evidence.slice(0, 3)) bullets.push({ tone: 'info', text: e })
    }
    const sec = sectorLine(d)
    if (sec) bullets.push(sec)
    for (const r of cleanReasons(d)) {
      if (/results|event|watch list|exchange/i.test(r) && !bullets.some((b) => b.text === r)) bullets.push({ tone: 'warn', text: r })
    }
    if (bullets.length === 0) bullets.push({ tone: 'ok', text: 'No special situation was named for this stock.' })
  } else if (n === 4) {
    const tr = d.honest_score?.track_record
    if (tr?.enough_evidence && tr.n != null && tr.hit_rate != null) {
      const hits = Math.round(tr.hit_rate * tr.n)
      bullets.push({ tone: 'info', text: `${tr.n} similar past cases: ${hits} reached the target, ${tr.n - hits} did not.` })
      bullets.push({ tone: 'info', text: 'Past results, not a promise.' })
    } else bullets.push({ tone: 'info', text: d.evidence_text || 'Not enough similar past cases to measure yet.' })
  } else if (n === 5) {
    if (pts != null) bullets.push({ tone: 'ok', text: `Score ${pts}${rank ? `, ${rankText(rank).toLowerCase()}` : ''}.` })
    else bullets.push({ tone: 'info', text: 'No score was stored for this stock.' })
    bullets.push({ tone: 'info', text: 'The score ranks the stocks against each other. It is not a chance of profit.' })
  } else {
    // The decision: put every stored thing for and against side by side, in plain words.
    bullets.push({ tone: word === 'TRADE' ? 'ok' : 'warn', text: word === 'TRADE' ? 'The brain says BUY.' : `The brain says ${word}, not BUY today.` })
    if (pts != null) bullets.push({ tone: 'info', text: `Score ${pts}${rank ? `, ${rankText(rank).toLowerCase()}` : ''}.` })
    const mode = run.banner.mode
    if (mode && mode !== 'NORMAL') bullets.push({ tone: 'warn', text: 'The market is careful today, so new buys need extra proof.' })
    const tb = trendBullet(d, run)
    if (tb) bullets.push(tb)
    const sec = sectorLine(d)
    if (sec) bullets.push(sec)
    links.push({ label: 'Open the stock page', to: `/trademind/stock/${sym}` }, { label: 'Open the Market page', to: '/trademind/market' })
  }
  return { bullets, links }
}

/** Decision-step "what would change it", without account figures. */
export function safeChanges(d: BrainDecision): string[] {
  return (d.what_would_change ?? [])
    .map((c) => c.text.trim())
    .filter((t) => t !== '' && !/₹|minimum|half size|half of this|room under|free room/i.test(t))
}
