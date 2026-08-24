// Small, literal icons — not decoration. Shared across pages so the same
// glyph always means the same thing (e.g. the building = large-cap/stability
// identity on both Suggestions and Recommendations, since they read the same
// model). All inherit `currentColor` so surrounding CSS controls their color.

export function BuildingIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path d="M4 21V9l8-6 8 6v12" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M9 21v-6h6v6" stroke="currentColor" strokeWidth="2" />
    </svg>
  )
}

export function ScaleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path
        d="M12 3v18M7 7l-4 6h8l-4-6zM17 7l-4 6h8l-4-6z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function SproutIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path d="M12 21c0-5 2-8 7-9-1 5-2 9-7 9z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M12 21c0-6-2-10-7-12 0 6 2 11 7 12z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  )
}

export function WarningIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none">
      <path d="M3 17l6-6 4 4 8-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M15 7h6v6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function LayersIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="10" width="18" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
      <path d="M7 10V7a5 5 0 0110 0v3" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

export function PlugIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none">
      <path
        d="M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-5 5 5 5 0 0 1-5-5V8zM12 16v5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function ClockIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 7v5l4 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

export function SendIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none">
      <path d="M21 3 3 10.5l7 3 3 7L21 3z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  )
}
