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

export const chanceTitle = (d: BrainDecision): string => {
  const h = d.honest_score
  if (!h) return 'No score for this stock.'
  if (h.status === 'not_measured') return h.note ?? 'No measured chance for this model.'
  return `Estimated chance of +8% before −4% within 15 trading days, from how this score did on days the model had not seen. ${h.track_record?.text ?? ''}`.trim()
}

/** Plain-English track record under an idea: how often similar ideas really worked. */
export function TrackRecord({ decision }: { decision: BrainDecision }) {
  const h = decision.honest_score
  if (!h) return null
  if (h.status === 'not_measured') return <p className="tm-note">{h.note}</p>
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
