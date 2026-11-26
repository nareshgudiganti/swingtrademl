// The trading numbers and the trial calendar, read from the backend (GET /config/trading-rules, #416).
// The frontend displays these; it never owns them. The app does not render until they are loaded
// (see TradingRulesGate), so a screen never shows a guessed number: if they cannot be loaded, the app says so.
//
// Display only: nothing here changes a decision, an order, sizing, a stop or a limit.

import type { TradingRulesDto } from '../api/types'

let current: TradingRulesDto | null = null

export function setTradingRules(rules: TradingRulesDto | null): void {
  current = rules
}

export function tradingRulesLoaded(): boolean {
  return current !== null
}

function loaded(): TradingRulesDto {
  // The gate keeps every screen from rendering before this is set; a missing value is a bug, never a guess.
  if (current === null) throw new Error('The trading rules are not loaded yet.')
  return current
}

/** Fractions from the server (0.08) as percent numbers (8), without floating-point noise. */
const pct = (fraction: number) => Math.round(fraction * 10000) / 100

/** The brain's plan in percent: +8 target, 4 stop (a positive number), 5 half-out, 15 sessions. */
export type Plan = { targetPct: number; stopPct: number; halfPct: number; days: number }

export function plan(): Plan {
  const p = loaded().brain_plan
  return { targetPct: pct(p.target_pct), stopPct: pct(p.stop_pct), halfPct: pct(p.half_out_pct), days: p.max_sessions }
}

/** One research horizon (5, 10 or 15 sessions) as the active config version states it. */
export function horizonRule(horizon: number) {
  const h = loaded().research.horizons.find((r) => r.horizon === horizon)
  if (!h) throw new Error(`The trading rules have no ${horizon}-day horizon.`)
  return { ...h, targetPct: pct(h.target_pct), stopPct: pct(h.stop_pct) }
}

/** The 5-session question the older models answer, as a sentence part: "+2% or more after 5 days". */
export const fiveDayQuestion = () => {
  const h = horizonRule(5)
  return `+${h.targetPct}% or more after ${h.max_sessions} days`
}

/** The same question in words for a sentence: "does the price close 2% or more higher within 5 days". */
export const fiveDayQuestionWords = () => {
  const h = horizonRule(5)
  return `does the price close ${h.targetPct}% or more higher within ${h.max_sessions} days`
}

/** "+8% target, −4% stop" style fragments, built once so every screen words them the same. */
export const targetText = () => `+${plan().targetPct}%`
export const stopText = () => `−${plan().stopPct}%`
export const halfText = () => `+${plan().halfPct}%`

/** The price at which half is sold: the entry price plus the served half-out percent. */
export const halfOutPrice = (entry: number) => entry * (1 + plan().halfPct / 100)

/** The drawdown that pauses new buys, in percent (read-only: the server enforces it). */
export const maxDrawdownPct = () => pct(loaded().risk_limits.max_drawdown_pct)

/** The window the brain's plan runs on, as the sentence parts screens reuse. */
export const planDays = () => plan().days

/** Trial calendar: first session, sessions needed, and the market holidays. */
export function trial() {
  const t = loaded().trial
  return { start: t.start, minSessions: t.min_sessions, sessionsSoFar: t.sessions_so_far }
}
export const holidays = (): readonly string[] => loaded().calendar.holidays
