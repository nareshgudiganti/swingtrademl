// The TradeMind screens' one path to real data: thin react-query wrappers
// around the brain endpoints, plus pure mappers that turn a BrainRun into
// the shapes a screen wants. No screen should call `api.brain*` directly —
// go through here so every screen loads, errors and goes stale the same way.
//
// Query keys for the parameterless calls (brainHealth, brainEpisodes,
// brainModules, brainLearning, brainProposals) match the ones Brain.tsx uses
// for the same endpoint, so the cache is shared between /brain and
// /trademind. useLatestRun is the one deliberate exception: it keys on
// ['brainLatest', 'nightly'] (Brain.tsx uses the bare ['brainLatest']) so
// that a future "why" or "intraday" run kind can get its own cache entry
// without colliding with the nightly one every TradeMind screen reads.

import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { ApiError, api } from '../api/client'
import type { BrainDecision, BrainRun, BrainSituation } from '../api/types'

// ----------------------------------------------------------------- status --

/** The word the brain actually settled on: an owner's overrule, if any,
 * otherwise its own word. Mirrors Brain.tsx's private finalWord(). */
function finalWord(d: BrainDecision): string {
  return d.overruled_word ?? d.word
}

export function useLatestRun(): UseQueryResult<BrainRun> {
  return useQuery({
    queryKey: ['brainLatest', 'nightly'],
    queryFn: () => api.brainLatestRun('nightly'),
    retry: false,
  })
}

/**
 * 'live'    — the latest run loaded (even if it has zero decisions yet).
 * 'off'     — /brain/* answers 404 for everything: BRAIN_ENABLED is false.
 * 'loading' — still waiting to find out which of the above it is.
 * 'error'   — a real failure (not a 404) talking to the brain.
 *
 * /brain/runs/latest 404s both when the brain is switched off AND when it's
 * on but has never run yet — the same status code means two different
 * things. We tell them apart with /brain/modules: that endpoint only 404s
 * when the whole brain router is off. If modules loads fine while runs/
 * latest 404s, the brain is live and screens should render their own empty
 * state ("no run yet"), not a "brain off" message.
 */
export function useBrainStatus(): 'live' | 'off' | 'loading' | 'error' {
  const latest = useLatestRun()
  const modules = useModules()

  if (latest.isSuccess) return 'live'

  const latestIs404 = latest.error instanceof ApiError && latest.error.status === 404
  if (!latestIs404) {
    if (latest.isError) return 'error'
    return 'loading'
  }

  // latest is a 404 — ambiguous until modules resolves.
  if (modules.isSuccess) return 'live'
  const modulesIs404 = modules.error instanceof ApiError && modules.error.status === 404
  if (modulesIs404) return 'off'
  if (modules.isError) return 'error'
  return 'loading'
}

// ---------------------------------------------------------------- mappers --
// Pure functions, no hooks — easy to unit-test later and safe to call from
// render.

/** Idea decisions (not holdings), TRADE/WATCH first, then by confidence
 * descending. Uses the owner's overruled word when there is one, same as
 * the brain console. */
export function ideasFrom(run: BrainRun): BrainDecision[] {
  const rank = (d: BrainDecision) => (['TRADE', 'WATCH'].includes(finalWord(d)) ? 0 : 1)
  return run.decisions
    .filter((d) => d.kind === 'idea')
    .slice()
    .sort((a, b) => {
      const r = rank(a) - rank(b)
      if (r !== 0) return r
      return (b.confidence ?? -1) - (a.confidence ?? -1)
    })
}

/** Holding decisions, in the order the brain returned them. */
export function holdingsFrom(run: BrainRun): BrainDecision[] {
  return run.decisions.filter((d) => d.kind === 'holding')
}

/** The one market-wide situation (if the brain recognised one this run). */
export function marketSituation(run: BrainRun): BrainSituation | undefined {
  return run.situations.find((s) => s.scope === 'market')
}

/** Situations the brain recognised for one stock (a stock can have more
 * than one, or none). */
export function stockSituations(run: BrainRun, symbol: string): BrainSituation[] {
  return run.situations.filter((s) => s.scope === 'stock' && s.subject === symbol)
}

// ------------------------------------------------------------ thin queries --

export function useWhy(symbol?: string) {
  return useQuery({
    queryKey: ['brainWhy', symbol],
    queryFn: () => api.brainWhy(symbol!),
    enabled: !!symbol,
  })
}

export function useTrack(symbol?: string) {
  return useQuery({
    queryKey: ['brainTrack', symbol],
    queryFn: () => api.brainTrack(symbol!),
    enabled: !!symbol,
  })
}

export function useEpisodes() {
  return useQuery({ queryKey: ['brainEpisodes'], queryFn: api.brainEpisodes })
}

export function useModules() {
  return useQuery({ queryKey: ['brainModules'], queryFn: api.brainModules })
}

export function useHealth() {
  return useQuery({ queryKey: ['brainHealth'], queryFn: api.brainHealth })
}

export function useRuns(n?: number) {
  return useQuery({ queryKey: ['brainRuns', n], queryFn: () => api.brainRuns(n) })
}

export function useLearning() {
  return useQuery({ queryKey: ['brainLearning'], queryFn: () => api.brainLearning() })
}

export function useProposals() {
  return useQuery({ queryKey: ['brainProposals'], queryFn: api.brainProposals })
}
