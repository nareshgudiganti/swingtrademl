import './beginner.css'
import type { EventItem } from './types'

export const NO_EVENTS = 'Nothing scheduled in the next 15 trading days'

/** Results and corporate actions, already worded and counted in trading days by the backend. */
export default function UpcomingEvents({ events }: { events: EventItem[] }) {
  if (events.length === 0) return <p className="tm-note">{NO_EVENTS}</p>
  return (
    <ul className="bx-plan">
      {events.map((e) => (
        <li key={`${e.symbol}-${e.kind}-${e.date}`}>{`${e.symbol}: ${e.plain}`}</li>
      ))}
    </ul>
  )
}
