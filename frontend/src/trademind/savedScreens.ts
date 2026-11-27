// Saved screens (#310, slice A): a person's named Discover filters, kept on the server. Pure functions only: turn the
// Discover controls into a saved spec, put a saved spec back on the controls, say plainly what is no longer available,
// and word the "what changed" note. Nothing here decides or ranks anything.
//
// Honesty rules: a saved value that no longer exists is shown as "no longer available" and is never replaced by
// another value (the list then shows its empty state, not a different list). The digest wording comes from the
// server, which takes it only from stored fields; this file adds no reason of its own.

import type { BrainDecision } from '../api/types'
import type { CapTier } from './cap'
import { DISCOVER_FILTERS, type DiscoverFilter } from './discoverRules'
import { DEFAULT_HORIZON, HORIZONS, horizonById, type HorizonId } from './horizons'
import { wordLabel } from './vocab'

export type Layout = 'table' | 'slides'

export type ScreenSpec = {
  horizon: string
  cap_tiers: string[]
  patterns: string[]
  word: string
  sector: string | null
  query: string
  layout: Layout
  watch_only: boolean
}

export type SavedScreen = {
  id: number
  name: string
  spec: ScreenSpec
  filters_version: number
  created_at: string | null
  updated_at: string | null
}

export type SavedScreens = { screens: SavedScreen[]; limit: number }

export type DigestSide = { word: string; rank: number | null; rank_of: number | null }
export type DigestRow = {
  symbol: string
  now: DigestSide | null
  before: DigestSide | null
  rank: number | null
  rank_of: number | null
  reason_code: string
  reason: string
}
export type DigestRun = { run_id: string; day: string; as_of: string; banner_mode: string | null }
export type ScreenDigest = {
  comparable: boolean
  note: string | null
  current: DigestRun | null
  previous: DigestRun | null
  came_in: DigestRow[]
  dropped_out: DigestRow[]
  not_compared: DigestRow[]
  footer: string
  screen?: { id: number | null; name: string }
}

/** What the Discover controls hold right now. */
export type Controls = { filter: DiscoverFilter; sector: string; query: string; layout: Layout }

export const MAX_NAME = 60

const CAP_LABEL: Record<string, string> = {
  large: 'Large companies',
  midcap: 'Mid-sized companies',
  smallcap: 'Small companies',
}

const isWord = (w: string): boolean => (DISCOVER_FILTERS as string[]).includes(w)

function horizonKnown(id: string): id is HorizonId {
  return HORIZONS.some((h) => h.id === id)
}

/** A fresh spec from the controls. Fields Discover has no control for keep what an opened screen already holds. */
export function specFromControls(c: Controls, base?: ScreenSpec | null): ScreenSpec {
  return {
    horizon: base?.horizon ?? DEFAULT_HORIZON,
    cap_tiers: base?.cap_tiers ?? [],
    patterns: base?.patterns ?? [],
    word: c.filter,
    sector: c.sector || null,
    query: c.query.trim().slice(0, 32),
    layout: c.layout,
    watch_only: base?.watch_only ?? false,
  }
}

/** The controls a saved spec sets. A word the app does not know leaves "All" on the control only; screenProblems()
 *  still reports it, and listBlocked() keeps the list empty, so it is never hidden. */
export function controlsFromSpec(spec: ScreenSpec): Controls {
  return {
    filter: isWord(spec.word) ? (spec.word as DiscoverFilter) : 'ALL',
    sector: spec.sector ?? '',
    query: spec.query ?? '',
    layout: spec.layout === 'slides' ? 'slides' : 'table',
  }
}

/** What in a saved screen cannot be applied right now, in plain words. Empty = everything can be applied.
 *  `sectors` is the list of sectors on this run, or null while it is not known (then a sector is not judged). */
export function screenProblems(spec: ScreenSpec, sectors: string[] | null): string[] {
  const out: string[] = []
  if (!horizonKnown(spec.horizon)) {
    out.push(`The time window “${spec.horizon}” is no longer available.`)
  } else if (!horizonById(spec.horizon).available) {
    const h = horizonById(spec.horizon)
    out.push(`${h.title}: ${h.availabilityText.toLowerCase()}, so there is nothing to show for this window.`)
  }
  if (!isWord(spec.word)) out.push(`The word “${spec.word}” is no longer available.`)
  if (spec.sector && sectors && !sectors.includes(spec.sector)) out.push(`The sector “${spec.sector}” is no longer available.`)
  if (spec.patterns.length > 0) {
    out.push(`Pattern filters (${spec.patterns.join(', ')}) are not available on this list yet, so nothing is shown.`)
  }
  return out
}

/** Nothing is shown when a saved window, word or pattern cannot be applied: never a different list. A sector that is
 *  gone filters to nothing by itself (no stock is in it). */
export function listBlocked(spec: ScreenSpec): boolean {
  return !horizonKnown(spec.horizon) || !horizonById(spec.horizon).available || !isWord(spec.word) || spec.patterns.length > 0
}

/** The saved company-size and watchlist-only filters, applied to the ideas on screen. `tierOf` maps SYMBOL to its
 *  size (missing = unknown, which never matches a size filter); `watch` is my watchlist's symbols, or null while
 *  unknown (then nothing is shown rather than everything). */
export function applyExtras(
  ideas: BrainDecision[],
  spec: ScreenSpec,
  ctx: { tierOf: (symbol: string) => CapTier | string | undefined; watch: Set<string> | null },
): BrainDecision[] {
  return ideas.filter((d) => {
    const sym = d.symbol.toUpperCase()
    if (spec.cap_tiers.length > 0 && !spec.cap_tiers.includes(String(ctx.tierOf(sym) ?? ''))) return false
    if (spec.watch_only && !(ctx.watch?.has(sym) ?? false)) return false
    return true
  })
}

/** "Large companies, BUY, matching “KEI”": the read-back line under the menu and in the save box. */
export function describeSpec(spec: ScreenSpec): string {
  const parts: string[] = [horizonKnown(spec.horizon) ? horizonById(spec.horizon).title : spec.horizon]
  if (spec.cap_tiers.length > 0) parts.push(spec.cap_tiers.map((t) => CAP_LABEL[t] ?? t).join(' or '))
  if (spec.patterns.length > 0) parts.push(spec.patterns.join(' or '))
  if (spec.word !== 'ALL') parts.push(wordLabel(spec.word))
  if (spec.sector) parts.push(spec.sector)
  if (spec.query) parts.push(`matching “${spec.query}”`)
  if (spec.watch_only) parts.push('my watchlist only')
  if (parts.length === 1) parts.push('every stock')
  return parts.join(', ')
}

/** Do these controls still equal what was saved (the fields Discover has controls for)? */
export function sameAsSaved(spec: ScreenSpec, c: Controls): boolean {
  const mine = specFromControls(c, spec)
  return mine.word === spec.word && (mine.sector ?? '') === (spec.sector ?? '') && mine.query === spec.query && mine.layout === spec.layout
}

/** "3rd of 120": a place in the ranking, never the raw score. */
export function placeText(rank: number | null, of: number | null): string | null {
  if (rank == null || of == null) return null
  const tens = rank % 100
  const suffix = tens >= 11 && tens <= 13 ? 'th' : (({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[rank % 10] ?? 'th')
  return `${rank}${suffix} of ${of}`
}

/** "WAIT → BUY" for a stock whose word changed; null when it did not (or one side is missing). */
export function wordMove(row: DigestRow): string | null {
  if (!row.now || !row.before || row.now.word === row.before.word) return null
  return `${wordLabel(row.before.word)} → ${wordLabel(row.now.word)}`
}

/** The plain line when there is nothing to compare yet. */
export const NOT_ENOUGH_HISTORY = 'Not enough scan history yet to say what changed.'

export function digestIsEmpty(d: ScreenDigest): boolean {
  return d.came_in.length === 0 && d.dropped_out.length === 0 && d.not_compared.length === 0
}
