// The one recommendation card (bx6, oa12). Today and Discover show every brain idea with it, so a stock reads
// the same wherever it appears. Display only: every figure comes from the brain's stored decision or the
// read-only /beginner/stock brief. Nothing here works out a price, a size or a rule.
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { HoldingWord } from '../../api/types'
import { chanceText, chanceTitle } from '../honest'
import { HORIZONS } from '../horizons'
import { SCORE_HINT, scoreLabelLong } from '../scoreText'
import type { Action } from '../types'
import { ActionPill, Tag, inr } from '../ui'
import { WhatWouldChange } from '../WhatWouldChange'
import { NOTHING_STORED, whyNotTrade } from '../whyNotTrade'
import './beginner.css'
import { EXPERIMENTAL, MODEL_STATUS, NA, dayText, isCalibrated, withoutScorePercent } from './cardText'
import MoneyAtStake from './MoneyAtStake'
import type { BeginnerDecision, EventItem, MoneyAtStakeData, StockBriefData } from './types'

/** The plan part of the stock brief: the sell-half price and the last exit day, worked out by the backend. */
export type PlanData = Pick<StockBriefData['q3_plan'], 'available' | 'why' | 'sell_half_price' | 'sell_half_pct' | 'last_exit_day'>

const price = (n: number | null | undefined) => (n == null ? NA : `₹${inr(n)}`)
const RISK_RULE = /risk|limit|cap\b|drawdown|sector|blocked|no new trades/i

/** The owner's overrule (always more careful) wins — same rule as strategies/brain.py effective_word. */
export const effectiveWord = (d: BeginnerDecision) => d.overruled_word ?? d.word

function Word({ d }: { d: BeginnerDecision }) {
  const word = effectiveWord(d)
  return d.kind === 'idea' ? <ActionPill action={word as Action} /> : <Tag tone="blue">{word as HoldingWord}</Tag>
}

/** The time window chip, from the shared horizon table (../horizons.ts). The experimental label sits beside it. */
function horizonChip(days: number): string {
  const h = HORIZONS.find((x) => x.days === days)
  return h && h.available ? `${days} trading days` : `${days} trading days — no supported strategy for this window`
}

/** The brain's reasons in plain words. A WATCH/WAIT/AVOID idea uses the "why not TRADE" wording; anything
 *  else shows the stored lines. Raw model scores never keep a % sign. */
function reasonLines(d: BeginnerDecision): string[] {
  if (d.kind === 'idea' && effectiveWord(d) !== 'TRADE') {
    const items = whyNotTrade(d)
    if (items.length > 0) return items.map((i) => withoutScorePercent(i.detail ? `${i.text} (${i.detail})` : i.text))
  }
  return d.reasons.filter((r) => r.trim() !== '').map(withoutScorePercent)
}

/** What the risk check did with this idea, in one line. */
function riskVerdict(d: BeginnerDecision, isTrade: boolean, rule: string | undefined): string {
  if (d.kind !== 'idea') return 'Risk verdict: checks apply to new buys only — this is a stock already held.'
  if (d.downgraded_from && d.downgraded_from !== d.word) {
    return `Risk verdict: lowered from ${d.downgraded_from} to ${d.word}${
      d.downgrade_reason ? ` — ${withoutScorePercent(d.downgrade_reason)}` : ''
    }`
  }
  if (isTrade) {
    if (d.qty > 0) return `Risk verdict: passed — the paper account may buy ${d.qty} shares.`
    return rule ? `No shares allowed: ${withoutScorePercent(rule)}` : 'No shares allowed: the brain stored no reason.'
  }
  return `Risk verdict: nothing to check — the final decision is ${effectiveWord(d)}, so there is no trade.`
}

function Evidence({ d }: { d: BeginnerDecision }) {
  const h = d.honest_score
  let line: string
  if (h && isCalibrated(d)) {
    const tr = h.track_record
    line = tr?.enough_evidence && tr.text
      ? `Past results: ${withoutScorePercent(tr.text)}${h.caveat ? ` ${h.caveat}` : ''}`
      : `Past results: ${NA} — too few comparable past ideas to quote a hit rate.`
  } else if (h?.status === 'not_measured') {
    line = `Past results: ${NA} — ${h.note ?? "this model's score has not been checked against real results"}`
  } else {
    line = `Past results: ${NA} — there is no measured record for this kind of ${d.kind === 'idea' ? 'idea' : 'holding'}.`
  }
  return (
    <p className="bx-small" data-part="evidence">
      {line}
    </p>
  )
}

export default function IdeaCard({
  decision: d,
  money,
  plan,
  events,
  compact,
  actions,
  dayScores,
  linkTo,
  tags,
}: {
  decision: BeginnerDecision
  money?: MoneyAtStakeData
  /** From the stock brief. Missing → the sell-half price and last exit day say why. */
  plan?: PlanData
  events?: EventItem[]
  compact?: boolean
  /** Page buttons (e.g. the tester's paper buy). */
  actions?: ReactNode
  /** Every idea score in the same run, so the score can be shown as "Rank 2 of 9 today". */
  dayScores?: readonly (number | null)[]
  /** The stock page, when the card sits inside a router. */
  linkTo?: string
  /** Extra labels beside the name (e.g. the company size flag). */
  tags?: ReactNode
}) {
  const entry =
    d.entry_low == null || d.entry_high == null
      ? `${NA} — the brain stored no buy zone`
      : d.entry_low === d.entry_high
        ? price(d.entry_low)
        : `${price(d.entry_low)} to ${price(d.entry_high)}`
  const rule = d.reasons.find((r) => RISK_RULE.test(r))
  const word = effectiveWord(d)
  // Only a TRADE idea comes with a buy plan and rupees at stake; WATCH/WAIT/AVOID, holdings
  // and an owner overrule away from TRADE never show a buy zone (a beginner reads it as advice).
  const isTrade = d.kind === 'idea' && word === 'TRADE'
  const planWhy = plan ? (plan.why ?? 'no reason given') : 'the plan details were not loaded'
  const reasons = reasonLines(d)
  const shown = compact ? reasons.slice(0, 1) : reasons
  const more = compact ? reasons.slice(1) : []

  return (
    <div className="tm-card bx-card" data-card="idea" data-symbol={d.symbol}>
      <div className="bx-row">
        {linkTo ? (
          <Link className="bx-sym tm-link" to={linkTo}>
            {d.symbol}
          </Link>
        ) : (
          <span className="bx-sym">{d.symbol}</span>
        )}
        {tags}
        <Word d={d} />
        <Tag tone="violet">{horizonChip(d.horizon_days)}</Tag>
        <Tag tone="amber">{EXPERIMENTAL}</Tag>
      </div>

      <div data-part="score">
        {d.confidence == null ? (
          <span>{`Model score: ${NA} — the model gave no score for this stock`}</span>
        ) : (
          <span>{scoreLabelLong(d.confidence, dayScores)}</span>
        )}
        <div className="bx-small">{SCORE_HINT}</div>
        {isCalibrated(d) && (
          <div className="bx-small" title={chanceTitle(d)}>{`Estimated chance, measured on past days: ${chanceText(d)}`}</div>
        )}
      </div>

      {d.overruled_word && (
        <p className="tm-note">{`You overruled the brain to ${d.overruled_word}: ${d.overrule_reason ?? 'no reason given'} (the brain itself said ${d.word})`}</p>
      )}

      {isTrade ? (
        <ul className="bx-plan" data-part="plan">
          <li>{`Buy zone: ${entry}`}</li>
          <li>{`Target: ${d.target == null ? `${NA} — plan incomplete` : price(d.target)}`}</li>
          <li>{`Stop: ${d.stop == null ? `${NA} — plan incomplete` : price(d.stop)}`}</li>
          <li>
            {plan?.available && plan.sell_half_price != null
              ? `Sell half at: ${price(plan.sell_half_price)}`
              : `Sell half at: ${NA} — ${planWhy}`}
          </li>
          <li>
            {plan?.available && plan.last_exit_day
              ? `Last exit day: ${dayText(plan.last_exit_day)} (within ${d.horizon_days} trading days)`
              : `Last exit day: ${NA} — ${planWhy}`}
          </li>
        </ul>
      ) : (
        <div data-part="plan">{`No buy plan — the brain says ${word}`}</div>
      )}

      <div data-part="risk">{riskVerdict(d, isTrade, rule)}</div>

      {isTrade && d.qty > 0 && (
        <div data-part="money">
          <div>{`Shares (paper account): ${d.qty}`}</div>
          <MoneyAtStake
            value={money ?? { available: false, why: 'figures not loaded' }}
            halfPct={plan?.available ? plan.sell_half_pct : undefined}
          />
        </div>
      )}

      <div data-part="reasons">
        <div className="tm-strong">{d.overruled_word ? "The brain's own reasons" : 'Why the brain says this'}</div>
        {reasons.length === 0 ? (
          <p className="tm-dim">{`${NA} — ${NOTHING_STORED.toLowerCase()}`}</p>
        ) : (
          <ul className="bx-reasons">
            {shown.map((r, i) => (
              <li key={`${i}-${r}`}>{r}</li>
            ))}
          </ul>
        )}
        {more.length > 0 && (
          <details>
            <summary>{`${more.length} more reason${more.length === 1 ? '' : 's'}`}</summary>
            <ul className="bx-reasons">
              {more.map((r, i) => (
                <li key={`${i}-${r}`}>{r}</li>
              ))}
            </ul>
          </details>
        )}
        {!compact && d.evidence_text && <p className="tm-note">{withoutScorePercent(d.evidence_text)}</p>}
        {!compact && <WhatWouldChange decision={d} />}
      </div>

      {events && events.length > 0 && (
        <ul className="bx-plan">
          {events.map((e, i) => (
            <li key={`${i}-${e.kind}-${e.date}`}>{e.plain}</li>
          ))}
        </ul>
      )}

      <Evidence d={d} />
      <p className="bx-small" data-part="model-status">
        {MODEL_STATUS}
      </p>

      {actions && <div className="bx-actions">{actions}</div>}
    </div>
  )
}
