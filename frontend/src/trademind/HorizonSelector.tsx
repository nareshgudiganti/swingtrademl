// The shared horizon selector (Phase 3a). Every screen that lets someone pick a time window uses this, so the
// availability and validation labels are the same everywhere. Choosing a window with no supported strategy shows
// HorizonUnavailable, never another window's ideas.

import { HORIZONS, VALIDATION_TEXT, type Horizon, type HorizonId } from './horizons'

function statusText(h: Horizon): string {
  return h.validation ? VALIDATION_TEXT[h.validation] : h.availabilityText
}

export function HorizonSelector({
  value,
  onChange,
  variant = 'cards',
  count,
}: {
  value: HorizonId
  onChange: (id: HorizonId) => void
  variant?: 'cards' | 'pills'
  /** Number of ideas for the supported horizon (pills only). */
  count?: number
}) {
  if (variant === 'pills') {
    return (
      <div className="tm-dash-pilltabs" role="tablist" aria-label="Trading horizon (list)">
        {HORIZONS.map((h) => (
          <button
            key={h.id}
            type="button"
            role="tab"
            aria-selected={h.id === value}
            data-horizon={h.id}
            className={h.id === value ? 'active' : ''}
            title={statusText(h)}
            onClick={() => onChange(h.id)}
          >
            {h.title} ({h.available && count != null ? count : '—'})
          </button>
        ))}
      </div>
    )
  }
  return (
    <div className="tm-dash-tabs" role="tablist" aria-label="Trading horizon">
      {HORIZONS.map((h) => (
        <button
          key={h.id}
          type="button"
          role="tab"
          aria-selected={h.id === value}
          data-horizon={h.id}
          className={`tm-dash-tab tm-dash-tab-${h.id} ${h.id === value ? 'active' : ''}`}
          onClick={() => onChange(h.id)}
        >
          <strong>{h.title}</strong>
          <span>{h.available ? `${h.kind}, ${h.span}` : h.kind}</span>
          <small className={h.validation ? 'tm-horizon-experimental' : undefined}>{statusText(h)}</small>
        </button>
      ))}
    </div>
  )
}

/** What a screen shows for a horizon with no supported trading strategy: an explanation and no ideas. */
export function HorizonUnavailable({ horizon: h }: { horizon: Horizon }) {
  return (
    <div className="tm-horizon-unavailable" style={{ padding: '0.6rem 0.2rem' }}>
      <p>
        <strong>No supported trading strategy for {h.title}.</strong> TradeMind has no trading idea for this window,
        so none is shown. It will not show ideas made for another window under this name.
      </p>
      {h.research && <p className="tm-dim">{h.research}</p>}
    </div>
  )
}
