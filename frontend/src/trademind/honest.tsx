import type { BrainDecision } from '../api/types'

/** What an idea's score really meant on days the model had not seen (the API's `honest_score`).
 *  The raw model score is a ranking, never shown as a chance. */
export const chancePercent = (d: BrainDecision): number | null => {
  const h = d.honest_score
  return h && h.honest_chance != null ? Math.round(h.honest_chance * 100) : null
}

export const chanceText = (d: BrainDecision): string => {
  const p = chancePercent(d)
  return p == null ? '—' : `~${p}%`
}

/** What an estimated chance is a chance of, in plain English, as short visible text: a phone has no tooltip, so
 *  the scale cannot live only in `chanceTitle`. Read from the rule the server sent (h.rule); the 15-day text is the
 *  fallback when it sent none. Empty when there is no measured chance, so none of it ever shows without one. */
const FALLBACK_SCALE = 'aims for +8% target before the −4% stop, within 15 trading days (15-day trial)'

export const chanceScale = (d: BrainDecision): string => {
  if (chancePercent(d) == null) return ''
  const rule = d.honest_score?.rule
  // the server writes "-4%" with a hyphen; the screen writes a real minus
  return rule ? `aims for ${rule.replace(/-(?=\d)/g, '−')} (trial)` : FALLBACK_SCALE
}

export const chanceTitle = (d: BrainDecision): string => {
  const h = d.honest_score
  if (!h) return 'No score for this stock.'
  if (h.status === 'not_measured' || h.status === 'unverified') return h.note ?? 'No measured chance for this model.'
  return `The Brain's 15-day trial estimate: chance of +8% before −4% within 15 trading days, from how this score did on days the model had not seen. ${h.track_record?.text ?? ''}`.trim()
}

/** Plain-English track record under an idea: how often similar ideas really worked. */
export function TrackRecord({ decision }: { decision: BrainDecision }) {
  const h = decision.honest_score
  if (!h) return null
  if (h.status === 'not_measured' || h.status === 'unverified') return <p className="tm-note">{h.note}</p>
  const tr = h.track_record
  return (
    <div className="tm-note" style={{ marginTop: '0.5rem' }}>
      {tr?.enough_evidence ? (
        <p style={{ margin: 0 }}>{tr.text}</p>
      ) : (
        <p style={{ margin: 0 }}>Too few comparable past ideas to quote a hit rate.</p>
      )}
      {h.rule && (
        <p style={{ margin: '0.25rem 0 0' }}>
          Rule: {h.rule}. {h.caveat}
        </p>
      )}
      {h.note && <p style={{ margin: '0.25rem 0 0' }}>{h.note}</p>}
      <p style={{ margin: '0.25rem 0 0' }}>
        TradeMind still ranks and decides using the model’s ranking score. The estimated chance and track
        record above are for your information; they do not change the decision.
      </p>
    </div>
  )
}
