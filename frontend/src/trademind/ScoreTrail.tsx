// A held stock's strength score, day by day: "bought at 91 → 89 → 80 → 70 → 50".
// Plain words on purpose: the score is how strongly the model likes the stock
// today, out of 100. It is shown next to the stop-loss and the brain's verdict,
// never instead of them, and days with no reading are simply left out.

import type { DetailedPosition } from '../api/types'
import { Tag } from './ui'

type Trail = Pick<DetailedPosition, 'entry_confidence' | 'last_confidence' | 'score_trail' | 'score_band' | 'score_from_trail'>

const BAND: Record<string, { label: string; tone: 'green' | 'amber' | 'red'; color: string }> = {
  strong: { label: 'Strong', tone: 'green', color: 'var(--tm-green)' },
  easing: { label: 'Easing', tone: 'amber', color: 'var(--tm-amber)' },
  weak: { label: 'Weak', tone: 'red', color: 'var(--tm-red)' },
}

const score = (v: number) => Math.round(v * 100)
const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null
  const w = 120
  const h = 34
  const x = (i: number) => (i / (values.length - 1)) * (w - 6) + 3
  const y = (v: number) => h - 3 - Math.max(0, Math.min(1, v)) * (h - 6)
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Strength score over the recent days">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1]!)} r={3} fill={color} />
    </svg>
  )
}

/** Whole trail for one position. `compact` is the one-line version for tables. */
export default function ScoreTrail({ p, compact = false }: { p: Trail; compact?: boolean }) {
  const trail = p.score_trail ?? []
  // A brain position's entry/last numbers are not the same kind of score as the
  // daily one, so only its own day-by-day readings are shown.
  const fromTrail = p.score_from_trail === true
  const entry = fromTrail ? null : p.entry_confidence
  const now = fromTrail ? (trail[trail.length - 1]?.score ?? null) : p.last_confidence
  if (entry == null && now == null && trail.length === 0) {
    return <span className="tm-dim">No score yet</span>
  }

  const band = p.score_band ? BAND[p.score_band] : undefined
  const values = [...(entry != null ? [entry] : []), ...trail.map((t) => t.score)]
  const latest = now ?? trail[trail.length - 1]?.score ?? entry
  const drop = entry != null && latest != null ? score(entry) - score(latest) : 0
  const color = band?.color ?? 'var(--tm-violet)'

  if (compact) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        <span className="tm-num tm-strong">
          {entry != null ? `${score(entry)} → ` : ''}{latest != null ? score(latest) : '—'}
        </span>
        {band && <Tag tone={band.tone}>{band.label}</Tag>}
      </span>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <Sparkline values={values} color={color} />
        <div>
          <div className="tm-num" style={{ fontSize: '1.4rem', fontWeight: 700, color }}>
            {latest != null ? score(latest) : '—'}
            <span className="tm-dim" style={{ fontSize: '0.8rem', fontWeight: 400 }}> / 100 today</span>
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
            {band && <Tag tone={band.tone}>{band.label}</Tag>}
            {entry != null && drop >= 5 && <span className="tm-neg">Down {drop} since you bought it</span>}
            {entry != null && drop <= -5 && <span className="tm-pos">Up {-drop} since you bought it</span>}
          </div>
        </div>
      </div>

      <div className="tm-flex tm-wrap" style={{ gap: '0.4rem', marginTop: '0.6rem' }}>
        {entry != null && (
          <span className="tm-callout" style={{ padding: '0.2rem 0.5rem' }} title="Score when you bought it">
            <span className="tm-dim">Bought </span>
            <span className="tm-num tm-strong">{score(entry)}</span>
          </span>
        )}
        {trail.map((t) => (
          <span
            key={t.date}
            className="tm-callout"
            style={{ padding: '0.2rem 0.5rem' }}
            title={`${BAND[t.band]?.label ?? t.band} on ${shortDate(t.date)}`}
          >
            <span className="tm-dim">{shortDate(t.date)} </span>
            <span className="tm-num tm-strong" style={{ color: BAND[t.band]?.color }}>{score(t.score)}</span>
          </span>
        ))}
        {trail.length === 0 && (
          <span className="tm-dim">The day-by-day list starts with the next daily check.</span>
        )}
      </div>
      <p className="tm-dim" style={{ fontSize: '0.75rem', margin: '0.5rem 0 0' }}>
        Strength score: how strongly the model likes this stock today, out of 100. It is not a chance of profit,
        and a falling score is a heads-up, not a sell order. Days with no reading are left out.
      </p>
    </div>
  )
}
