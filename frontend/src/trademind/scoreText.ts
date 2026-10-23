// ux10: one place that turns the model score into words. The score (the API's `confidence`, 0-1) only ranks
// stocks against each other on the same day. It is NOT a chance of profit: in the trial data the 70+ group
// reached +8% only about 1 time in 8. So it is never shown with a % sign or called a chance.
// Where the day's other ideas are known it is shown as a place in the ranking ("Rank 3 of 12 today");
// otherwise as a plain number with a reminder of what it is not.
//
// The calibrated estimate in honest.tsx (`honest_score.honest_chance`) is a real measured chance and is
// not handled here.

/** The short hint shown wherever the score appears. */
export const SCORE_HINT = "A ranking among today's ideas, not a chance of making money."

/** What the bare number is not, for places where no ranking is available. */
export const SCORE_NOTE = 'a ranking number, not a chance of profit'

/** The score as a whole number from 0 to 100, or null when there is none. */
export function scorePoints(score: number | null | undefined): number | null {
  if (score == null || !Number.isFinite(score)) return null
  return Math.round(Math.max(0, Math.min(1, score)) * 100)
}

export type ScoreRank = { rank: number; of: number }

/** Place of `score` among the day's scores (highest = 1; equal scores share a place). Null if `score` is not
 *  one of them. */
export function scoreRank(score: number | null | undefined, dayScores: readonly (number | null | undefined)[]): ScoreRank | null {
  if (score == null || !Number.isFinite(score)) return null
  const scores = dayScores.filter((s): s is number => s != null && Number.isFinite(s))
  if (!scores.includes(score)) return null
  return { rank: 1 + scores.filter((s) => s > score).length, of: scores.length }
}

/** "Rank 3 of 12 today". */
export const rankText = (r: ScoreRank): string => `Rank ${r.rank} of ${r.of} today`

/** Short label: the rank when the day's scores are given and include this one, else "Model score 72".
 *  "—" when there is no score. */
export function scoreLabel(score: number | null | undefined, dayScores?: readonly (number | null | undefined)[]): string {
  const r = dayScores ? scoreRank(score, dayScores) : null
  if (r) return rankText(r)
  const p = scorePoints(score)
  return p == null ? '—' : `Model score ${p}`
}

/** Longer label for sentences and detail rows: says what the number is not when no rank is available. */
export function scoreLabelLong(score: number | null | undefined, dayScores?: readonly (number | null | undefined)[]): string {
  const r = dayScores ? scoreRank(score, dayScores) : null
  if (r) return `${rankText(r)} by model score`
  const p = scorePoints(score)
  return p == null ? 'No model score' : `Model score ${p} (${SCORE_NOTE})`
}

/** A score band from the API ("70%-80%", "60-70%", "80%+") without the % sign: "70-80", "60-70", "80+". */
export const scoreBandText = (band: string): string => band.replace(/%/g, '').trim()

// "model scores this stock 72%", "(ml_main) scores this stock 72%", "Model score 72%", "scored 72%",
// "scored 70% to 80%", "buy level of 60%", "buy level to 70%", "buy level is 60%", "buy level 60%": a raw
// model score written as a percentage by the brain's stored lines (the brain itself is frozen, so the % is taken off on screen).
const RAW_SCORE_PCT =
  /\b(model scores?(?: this stock)?|scores this stock|model score|scored|buy level(?: of| to| is)?) (\d+(?:\.\d+)?)%(?: to (\d+(?:\.\d+)?)%)?/gi

/** A stored brain line with any raw model score written without its % sign (it is a ranking, not a
 *  chance). Measured hit rates and calibrated chances in the same line are left as they are. */
export function withoutScorePercent(line: string): string {
  return line.replace(RAW_SCORE_PCT, (_m, lead: string, a: string, b?: string) =>
    b ? `${lead} ${a} to ${b}` : `${lead} ${a}`,
  )
}

/** A holding's one-line read from the server (`action_label`, e.g. "Still bullish (72% today) — …" or
 *  "Confidence easing (80% → 70%) today — …") with the model score shown as a plain number:
 *  "Still bullish (model score 72 today) — …", "Model score easing (80 → 70) today — …". */
export function actionLabelText(label: string): string {
  return label
    .replace(/\bConfidence easing \((\d+)% → (\d+)%\)/g, 'Model score easing ($1 → $2)')
    .replace(/\((\d+|\?)% today\)/g, '(model score $1 today)')
}
