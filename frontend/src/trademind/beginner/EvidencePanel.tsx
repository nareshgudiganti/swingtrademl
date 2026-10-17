import './beginner.css'
import { inr } from '../ui'
import { useEvidence } from './api'
import type { EvidenceSummary } from './types'

const NA = 'Not available'
const pct = (n: number) => `${n.toFixed(1)}%`

function Row({ label, value, why }: { label: string; value: number | null; why: string }) {
  return (
    <li>
      {label}: {value === null ? `${NA} — ${why}` : pct(value)}
    </li>
  )
}

/** Paper-only results of the bot, plus a sealed brain-trial count. No brain profit or win rate. */
export default function EvidencePanel({ evidence }: { evidence: EvidenceSummary }) {
  const { bot, brain_trial: brain, paper_label: label } = evidence
  const noPrices = 'no price history for those dates'
  return (
    <section className="bx-evidence">
      <h3>{`Results so far — ${label}`}</h3>
      {!bot.enough_trades && <p className="tm-note"><strong>{bot.note}</strong></p>}

      <h4>{`Version 1's practice money — ${label}`}</h4>
      <p className="bx-small">The brain&apos;s trial is not counted here; its results stay sealed below.</p>
      <ul className="bx-plan">
        <li>Profit booked: ₹{inr(bot.profit_booked)}</li>
        <li>Profit on open trades: ₹{inr(bot.profit_open)}</li>
        <li>Costs paid: ₹{inr(bot.costs_paid)}</li>
        <Row
          label="Worst fall from the top"
          value={bot.worst_fall_from_peak_pct}
          why="needs at least two days of account history"
        />
        <li>Finished trades: {bot.finished_trades}</li>
        <Row label="Win rate" value={bot.win_rate_pct} why="no finished trades yet" />
      </ul>

      <h4>{`Version 1 compared with the market — ${label}`}</h4>
      <ul className="bx-plan">
        <Row label="NIFTY 50 over the same days" value={bot.nifty_same_period_pct} why={noPrices} />
        <Row
          label="Every stock on the watchlist over the same days"
          value={bot.every_stock_same_period_pct}
          why={noPrices}
        />
      </ul>

      <h4>Brain trial</h4>
      <p>{`${brain.finished} of ${brain.needed} finished`}</p>
      <p className="tm-note">{brain.sealed_note}</p>
    </section>
  )
}

export function EvidencePanelLive() {
  const q = useEvidence()
  if (q.isLoading) return <p className="tm-note">Loading results…</p>
  if (q.isError || !q.data) return <p className="tm-note">{`${NA} — results could not be loaded`}</p>
  return <EvidencePanel evidence={q.data} />
}
