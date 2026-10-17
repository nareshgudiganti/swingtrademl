// Trading horizons: which time windows can produce a trading idea, and what evidence stands behind each.
// Owner decision 17 Oct (Phase 3a): two separate labels per horizon.
//  - Availability: does a supported trading strategy exist for this window?
//  - Validation: has that strategy shown acceptable evidence? (none has yet; 15 days is experimental)
// One table, so a horizon can later get its own model, evidence and status without redesigning screens.
// Labels only: nothing here changes what the brain decides or trades.

export type HorizonId = '1d' | '5d' | '15d' | '30d' | '90d'
export type Validation = 'experimental' | 'validated'

export type Horizon = {
  id: HorizonId
  days: number
  title: string
  kind: string
  span: string
  available: boolean
  availabilityText: string
  /** null when there is no strategy to validate. */
  validation: Validation | null
  /** Research predictions that exist for this window but are not a trading strategy. */
  research?: string
}

export const VALIDATION_TEXT: Record<Validation, string> = {
  experimental: 'Experimental, unproven',
  validated: 'Validated',
}

const NONE = 'No supported trading strategy'

export const HORIZONS: Horizon[] = [
  { id: '1d', days: 1, title: '1 Day', kind: 'Next day', span: '1 trading day', available: false, availabilityText: NONE, validation: null },
  {
    id: '5d',
    days: 5,
    title: '5 Days',
    kind: 'Short swing',
    span: '3 - 7 trading days',
    available: false,
    availabilityText: NONE,
    validation: null,
    research:
      'The older ML models make research predictions for this window (closes +2% or more after 5 days). ' +
      'They are unvalidated and not a trading plan.',
  },
  {
    id: '15d',
    days: 15,
    title: '15 Days',
    kind: 'Medium swing',
    span: 'up to 15 trading days',
    available: true,
    availabilityText: 'Trading ideas available',
    validation: 'experimental',
  },
  { id: '30d', days: 30, title: '30 Days', kind: 'Positional swing', span: '3 - 6 weeks', available: false, availabilityText: NONE, validation: null },
  { id: '90d', days: 90, title: '3 Months', kind: 'Long swing', span: '6 - 12 weeks', available: false, availabilityText: NONE, validation: null },
]

export const DEFAULT_HORIZON: HorizonId = '15d'

export function horizonById(id: HorizonId): Horizon {
  return HORIZONS.find((h) => h.id === id)!
}
