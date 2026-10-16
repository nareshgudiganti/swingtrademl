import type { HoldingWord } from '../../api/types'
import { chanceText, chancePercent, chanceTitle, TrackRecord } from '../honest'
import type { Action } from '../types'
import { ActionPill, Tag, inr } from '../ui'
import './beginner.css'
import MoneyAtStake from './MoneyAtStake'
import type { BeginnerDecision, EventItem, MoneyAtStakeData } from './types'

const NA = 'Not available'
const price = (n: number | null) => (n == null ? NA : `₹${inr(n)}`)
const RISK_RULE = /risk|limit|cap\b|drawdown|sector|blocked|no new trades/i

function Word({ d }: { d: BeginnerDecision }) {
  return d.kind === 'idea' ? (
    <ActionPill action={d.word as Action} />
  ) : (
    <Tag tone="blue">{d.word as HoldingWord}</Tag>
  )
}

export default function IdeaCard({
  decision: d,
  money,
  events,
  compact,
}: {
  decision: BeginnerDecision
  money?: MoneyAtStakeData
  events?: EventItem[]
  compact?: boolean
}) {
  const entry =
    d.entry_low == null || d.entry_high == null ? NA : `${price(d.entry_low)} to ${price(d.entry_high)}`
  const rule = d.reasons.find((r) => RISK_RULE.test(r))
  return (
    <div className="tm-card bx-card">
      <div className="bx-row">
        <span className="bx-sym">{d.symbol}</span>
        <Word d={d} />
        <Tag tone="violet">{`${d.horizon_days} trading days`}</Tag>
        <Tag tone="amber">Experimental, unproven</Tag>
      </div>

      <div>
        {d.confidence == null ? (
          <span>{`Score: ${NA} — the model gave no score`}</span>
        ) : (
          <span title={chanceTitle(d)}>{`${d.confidence} model score`}</span>
        )}
        <span className="bx-small"> — a ranking, not a chance of winning</span>
        {chancePercent(d) != null && <div className="bx-small">{`Estimated chance: ${chanceText(d)}`}</div>}
      </div>

      <ul className="bx-plan">
        <li>{`Buy zone: ${entry}`}</li>
        <li>{`Target: ${price(d.target)}`}</li>
        <li>{`Stop: ${d.stop == null ? `${NA} — plan incomplete` : price(d.stop)}`}</li>
        <li>{`Sell by: within ${d.horizon_days} trading days`}</li>
      </ul>

      <div>
        {d.qty > 0 ? (
          <>
            <div>{`Shares allowed: ${d.qty}`}</div>
            <MoneyAtStake value={money ?? { available: false, why: 'figures not loaded' }} />
          </>
        ) : (
          <div>{rule ? `No shares allowed: ${rule}` : 'No shares allowed'}</div>
        )}
      </div>

      {events && events.length > 0 && (
        <ul className="bx-plan">
          {events.map((e) => (
            <li key={`${e.kind}-${e.date}`}>{e.plain}</li>
          ))}
        </ul>
      )}

      {!compact && (
        <details>
          <summary>Why the brain says this</summary>
          <ul>
            {d.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {d.evidence_text && <p className="tm-note">{d.evidence_text}</p>}
          <TrackRecord decision={d} />
        </details>
      )}

      <p className="bx-small">Evidence: Not proven. How this kind of idea has done is not yet shown as proof.</p>
    </div>
  )
}
