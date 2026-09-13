// Plain-frontend risk read on a strategy — mirrors lib/tiers.ts: one small,
// pure module the whole app can share so "this strategy looks aggressive"
// means the same thing everywhere instead of three inline judgment calls.
//
// This is a heuristic, not a risk model — it only looks at three knobs
// already stored on the strategy (see db/models/trading.py Strategy and
// strategies/ml_swing.py) and turns them into a label + one plain-English
// sentence a non-expert user can read without knowing what any of the
// numbers mean. Backend defaults (core/config.py): stop_loss_pct 0.05,
// min_confidence 0.60 — the "moderate" bucket below is built around those.
export type RiskLabel = 'Conservative' | 'Moderate' | 'Aggressive'

export interface RiskAssessment {
  label: RiskLabel
  blurb: string
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

// Params key for "does this strategy's universe include small-caps" — small
// caps swing harder, so including them reads as more aggressive. Undefined
// (key not set) counts as neutral rather than guessing either way.
function smallcapIncluded(params: Record<string, unknown>): boolean | null {
  const value = params.include_smallcap ?? params.smallcap_included ?? params.smallcap
  return typeof value === 'boolean' ? value : null
}

/** Heuristic score for one strategy's params, -3 (most aggressive signals)
 * to +3 (most conservative). Each of the three signals contributes at most
 * one point either way; a signal that's absent or in the middle contributes
 * nothing, which is how "in between" params end up Moderate. */
function score(params: Record<string, unknown>): number {
  let total = 0

  const stopLoss = asNumber(params.stop_loss_pct)
  if (stopLoss !== null) {
    if (stopLoss <= 0.04) total += 1 // tight stop — cuts losses fast
    else if (stopLoss >= 0.07) total -= 1 // loose stop — rides out more pain
  }

  const minConfidence = asNumber(params.min_confidence)
  if (minConfidence !== null) {
    if (minConfidence >= 0.65) total += 1 // only very sure signals get acted on
    else if (minConfidence <= 0.55) total -= 1 // acts on weaker signals too
  }

  const smallcap = smallcapIncluded(params)
  if (smallcap === false) total += 1 // sticks to steadier, larger stocks
  else if (smallcap === true) total -= 1 // includes more volatile small-caps

  return total
}

const BLURBS: Record<RiskLabel, string> = {
  Conservative:
    'Tight stop-loss, a high confidence bar, and/or a steadier stock universe — fewer trades, aimed at protecting capital first.',
  Moderate: 'A balanced mix of stop-loss, confidence, and universe settings — not notably cautious or aggressive.',
  Aggressive:
    'Wider stop-loss, a lower confidence bar, and/or a wider (more volatile) stock universe — more trades, more risk for more upside.',
}

/** Turns a strategy's params into a plain-English risk read. `params` is
 * whatever the caller has on hand for the strategy — typically its `params`
 * JSON blob merged with the sibling `stop_loss_pct` column, since that knob
 * lives outside the JSON on the Strategy model itself. */
export function riskLabelFor(params: Record<string, unknown>): RiskAssessment {
  const total = score(params)
  const label: RiskLabel = total >= 2 ? 'Conservative' : total <= -2 ? 'Aggressive' : 'Moderate'
  return { label, blurb: BLURBS[label] }
}
