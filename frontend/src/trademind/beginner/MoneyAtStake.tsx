import { inr } from '../ui'
import './beginner.css'
import type { MoneyAtStakeData } from './types'

const NA = 'Not available'
const rupees = (n: number | null | undefined) => (n == null ? NA : `₹${inr(n)}`)

/** Rupees at stake, already after charges. Never derived here: every figure comes from the backend. */
export default function MoneyAtStake({ value }: { value: MoneyAtStakeData }) {
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
        <li>{`If half is sold at +5% and the rest at the target you gain about ${rupees(value.gain_if_half_out)}`}</li>
      </ul>
      <p className="bx-small">All figures are after charges.</p>
    </div>
  )
}
