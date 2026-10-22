import { inr } from '../ui'
import { useStockBrief } from './api'
import './beginner.css'
import MoneyAtStake from './MoneyAtStake'
import type { BriefAnswer, StockBriefData } from './types'
import UpcomingEvents from './UpcomingEvents'

const price = (n: number | undefined) => (n == null ? 'Not available' : `₹${inr(n)}`)

/** "16 Oct 2026" in India time, from the run's ISO timestamp. */
export function viewDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'Not available'
  return d.toLocaleDateString('en-GB', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric' })
}

function Section({ title, a, children }: { title: string; a: BriefAnswer; children?: React.ReactNode }) {
  return (
    <section className="tm-card bx-card">
      <h3>{title}</h3>
      {a.available ? (
        <>
          <p>{a.answer}</p>
          {children}
        </>
      ) : (
        <>
          <p>{a.answer}</p>
          <p className="tm-note">{`Why: ${a.why ?? 'no reason given'}`}</p>
        </>
      )}
    </section>
  )
}

/** Six plain questions about one stock. Takes data as a prop so it renders without network. */
export default function StockBrief({ data }: { data: StockBriefData }) {
  const plan = data.q3_plan
  const decision = data.q2_brain.decision
  return (
    <div className="bx-brief" data-testid="stock-brief">
      <p className="bx-small bx-brief-asof">
        {data.as_of ? `Brain's view from ${viewDate(data.as_of)}` : "Brain's view: Not available — no brain run on record yet"}
      </p>
      <Section title="What is this company?" a={data.q1_company} />
      <Section title="What does the brain say today, and why?" a={data.q2_brain}>
        {decision && (
          <ul className="bx-plan">
            {decision.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="What is the plan?" a={plan}>
        <ul className="bx-plan">
          <li>{`Buy zone: ${plan.buy_zone ? `${price(plan.buy_zone[0])} to ${price(plan.buy_zone[1])}` : 'Not available'}`}</li>
          <li>{`Sell half at: ${price(plan.sell_half_price)}`}</li>
          <li>{`Target: ${price(plan.target)}`}</li>
          <li>{`Stop: ${price(plan.stop)}`}</li>
          <li>{`Last day to be out: ${plan.last_exit_day ? viewDate(`${plan.last_exit_day}T12:00:00+05:30`) : 'Not available'}`}</li>
        </ul>
      </Section>
      <section className="tm-card bx-card">
        <h3>How much money is at stake?</h3>
        <MoneyAtStake value={data.q4_money} halfPct={plan.sell_half_pct} />
      </section>
      <Section title="Is anything coming up?" a={data.q5_events}>
        <UpcomingEvents events={data.q5_events.events ?? []} />
      </Section>
      <Section title="Has this kind of idea worked before?" a={data.q6_evidence}>
        <p className="bx-small">Evidence status from the Observatory. Not shown as proof unless it says Proven.</p>
      </Section>
    </div>
  )
}

export function StockBriefForSymbol({ symbol }: { symbol: string }) {
  const q = useStockBrief(symbol)
  if (q.isLoading) return <p className="tm-note">Loading…</p>
  if (q.error || !q.data) return <p className="tm-note">{`Not available — ${(q.error as Error | null)?.message ?? 'no data'}`}</p>
  return <StockBrief data={q.data} />
}
