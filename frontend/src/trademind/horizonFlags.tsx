// #326: one explicit flag per forecast horizon (5, 10 and 15 trading days), shown the same way on Today, Stock
// Detail and Idea reports. The score always comes from the 5-day models; the 10-day and 15-day windows are
// research only (or not served at all), so they are marked unavailable and never stand in for the 5-day score.
// The plan's day count is the longest hold, a separate thing from any forecast window.
//
// Labels only: every number comes from the served trading rules (tradingRules.ts). Nothing here changes a
// decision, a plan, an order or a stop.
import { horizonRule, plan } from './tradingRules'

export type HorizonFlagState = 'score' | 'unavailable'

export type HorizonFlag = {
  horizon: number
  state: HorizonFlagState
  /** Short pill text: "5D forecast: used for the score". */
  label: string
  /** One plain sentence for the tooltip. */
  detail: string
}

/** The forecast windows the app knows about. The score is read on the first one. */
const SCORE_HORIZON = 5
const FORECAST_HORIZONS = [SCORE_HORIZON, 10, 15] as const

function served(horizon: number) {
  try {
    return horizonRule(horizon)
  } catch {
    return null
  }
}

export function horizonFlags(): HorizonFlag[] {
  return FORECAST_HORIZONS.map((h) => {
    const rule = served(h)
    if (h === SCORE_HORIZON && rule) {
      return {
        horizon: h,
        state: 'score',
        label: `${h}D forecast: used for the score`,
        detail: `The score is the model’s ${rule.max_sessions}-day reading. It is a ranking, not a chance of profit.`,
      }
    }
    const why = rule?.research_only
      ? 'Research only: no model for this window feeds ideas yet.'
      : rule
        ? 'No model for this window scores stocks in the app yet.'
        : 'Not available.'
    return { horizon: h, state: 'unavailable', label: `${h}D forecast: not available`, detail: why }
  })
}

/** The plan's window, worded as a hold so it is never read as a forecast: "Up to 15-day hold". */
export const holdText = (days?: number | null): string => `Up to ${days ?? plan().days}-day hold`

export function HorizonFlags({ compact = false }: { compact?: boolean }) {
  const flags = horizonFlags()
  return (
    <div
      className="tm-horizon-flags"
      data-testid="horizon-flags"
      style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: compact ? 4 : 8, fontSize: compact ? 12 : 13 }}
    >
      {flags.map((f) => (
        <span
          key={f.horizon}
          className={`tm-dash-badge tm-horizon-flag tm-horizon-flag-${f.state}`}
          data-state={f.state}
          title={f.detail}
          style={f.state === 'unavailable' ? { opacity: 0.6 } : undefined}
        >
          {f.label}
        </span>
      ))}
      <span className="tm-dash-badge tm-horizon-flag tm-horizon-flag-hold" data-state="hold" title="When the plan sells at the latest. This is not a forecast window.">
        {holdText()}
      </span>
    </div>
  )
}
