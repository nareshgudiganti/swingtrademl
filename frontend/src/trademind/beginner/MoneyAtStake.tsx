import { inr } from '../ui'
import './beginner.css'
import type { MoneyAtStakeData } from './types'

const NA = 'Not available'
const rupees = (n: number | null | undefined) => (n == null ? NA : `${n < 0 ? '−' : ''}₹${inr(Math.abs(n))}`)

/** Rupees at stake, already after charges. Never derived here: every figure comes from the backend.
 *  `halfPct` is the backend's sell-half level (e.g. 0.05); without it the line says "the first target". */
export default function MoneyAtStake({ value, halfPct }: { value: MoneyAtStakeData; halfPct?: number }) {
  if (!value.available) {
    return (
      <div className="bx-money-block">
        <div className="bx-money-title">₹ at stake</div>
        <p className="tm-note">
          {`${NA} — ${value.why ?? 'no reason given'}`}
        </p>
      </div>
    )
  }
  return (
    <div className="bx-money-block">
      <div className="bx-money-title">₹ at stake</div>
      <ul className="bx-money">
        <li>{`Money put in: ${rupees(value.invested)}`}</li>
        <li>{`If the stop is hit you lose about ${rupees(value.loss_if_stop)}`}</li>
        <li>{`If the target is hit you gain about ${rupees(value.gain_if_target)}`}</li>
        <li>{`If half is sold ${halfPct != null ? `at +${Math.round(halfPct * 100)}%` : 'at the first target'} and the rest at the target you gain about ${rupees(value.gain_if_half_out)}`}</li>
      </ul>
      <p className="bx-small">All figures are after charges.</p>
    </div>
  )
}
