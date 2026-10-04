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

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, type UseQueryResult } from '@tanstack/react-query'

import { ApiError, api } from '../api/client'
import type { BrainDecision, BrainRun, BrainSituation } from '../api/types'

// ----------------------------------------------------------------- status --

/** The word the brain actually settled on: an owner's overrule, if any,
 * otherwise its own word. Mirrors Brain.tsx's private finalWord(). The one
 * copy every TradeMind screen imports — no more private per-page copies. */
export function finalWord(d: BrainDecision): string {
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
 * 'live'    — a latest run actually loaded: there IS a run to show.
 * 'no-run'  — the brain is switched on (modules answered) but has never
 *             produced a run yet. Distinct from 'live': nothing here claims
 *             a connection to a run that doesn't exist.
 * 'off'     — /brain/* answers 404 for everything: BRAIN_ENABLED is false.
 * 'loading' — still waiting to find out which of the above it is.
 * 'error'   — a real failure (not a 404) talking to the brain.
 *
 * /brain/runs/latest 404s both when the brain is switched off AND when it's
 * on but has never run yet — the same status code means two different
 * things. We tell them apart with /brain/modules: that endpoint only 404s
 * when the whole brain router is off. If modules loads fine while runs/
 * latest 404s, the brain is on but quiet ('no-run'); screens should render
 * their own "no run yet" empty state, not a "brain off" message.
 */
export function useBrainStatus(): 'live' | 'no-run' | 'off' | 'loading' | 'error' {
  const latest = useLatestRun()
  // A separate query from useModules(): this one exists only to settle the
  // off-vs-no-run question quickly, so unlike the shared useModules() (which
  // keeps Brain.tsx's default retries) it never retries a 404.
  const modules = useQuery({ queryKey: ['brainModules'], queryFn: api.brainModules, retry: false })

  if (latest.isSuccess) return 'live'

  const latestIs404 = latest.error instanceof ApiError && latest.error.status === 404
  if (!latestIs404) {
    if (latest.isError) return 'error'
    return 'loading'
  }

  // latest is a 404 — ambiguous until modules resolves.
  if (modules.isSuccess) return 'no-run'
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

/** api.brainWhy(symbol) STARTS A FRESH STORED BRAIN RUN on the server
 * (service.run_brain(kind="why"), ~15s) — it is not a cheap read. Never let
 * this refetch on its own: no polling, no refetch-on-focus, and cache it
 * forever once it answers. */
export function useWhy(symbol?: string) {
  return useQuery({
    queryKey: ['brainWhy', symbol],
    queryFn: () => api.brainWhy(symbol!),
    enabled: !!symbol,
    staleTime: Infinity,
    refetchInterval: false,
    refetchOnWindowFocus: false,
  })
}

/** A run's reasoning trace — the same query Brain.tsx uses (shared cache key
 * ['brainTrace', runId]), so a screen showing a decision that's already in
 * the latest run can read its trace without paying for a fresh brain run.
 * Same no-refetch rule as useWhy: the trace for a given run never changes. */
export function useRunTrace(runId?: string) {
  return useQuery({
    queryKey: ['brainTrace', runId],
    queryFn: () => api.brainRunTrace(runId!),
    enabled: !!runId,
    staleTime: Infinity,
    refetchInterval: false,
    refetchOnWindowFocus: false,
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

/** "Run the brain now": the request only queues the run (a full run takes
 *  minutes, longer than a web request may), then this checks it every 3 s
 *  until it is done or failed and calls `onFinished` once. After a page
 *  reload it picks up a run that is still waiting or thinking. */
export function useBrainRunNow(onFinished?: () => void) {
  const [runId, setRunId] = useState<string | null>(null)
  const recent = useQuery({ queryKey: ['brainRuns', 5], queryFn: () => api.brainRuns(5) })
  useEffect(() => {
    if (runId) return
    const active = recent.data?.find((r) => r.kind === 'nightly' && (r.status === 'queued' || r.status === 'running'))
    if (active) setRunId(active.run_id)
  }, [recent.data, runId])
  const start = useMutation({ mutationFn: api.brainRunNow, onSuccess: (q) => setRunId(q.run_id) })
  const run = useQuery({
    queryKey: ['brainRunNow', runId],
    queryFn: () => api.brainRunGet(runId!),
    enabled: !!runId,
    refetchInterval: (q) => {
      // Stop after a few failed checks in a row rather than ask forever.
      if (q.state.fetchFailureCount >= 3) return false
      const s = q.state.data?.status
      return !s || s === 'queued' || s === 'running' ? 3000 : false
    },
  })
  const lostTrack = !!runId && run.isError && run.failureCount >= 3
  const status = run.data?.status
  const finished = useRef<string | null>(null)
  useEffect(() => {
    if (runId && (status === 'done' || status === 'failed' || status === 'superseded') && finished.current !== runId) {
      finished.current = runId
      onFinished?.()
    }
  }, [status, runId, onFinished])
  return {
    start: () => start.mutate(),
    // Also "thinking" between a successful start and the first status check.
    thinking:
      start.isPending ||
      status === 'queued' ||
      status === 'running' ||
      (!!runId && !run.data && !lostTrack),
    status,
    run: run.data,
    alreadyRunning: start.data?.already_running ?? false,
    startError: start.error ?? (lostTrack ? new Error('Lost touch with the run; refresh the page to check on it.') : null),
  }
}

/** One plain line for where a queued run is, e.g. "Thinking… step 3 of 8". */
export function runNowLine(status?: string, progress?: { done: number; total: number | null; step: string | null } | null) {
  if (status === 'queued') return 'Waiting to start…'
  if (status === 'running') {
    if (progress?.total) return `Thinking… ${progress.done} of ${progress.total} steps done`
    return 'Thinking…'
  }
  return ''
}

export function useLearning() {
  return useQuery({ queryKey: ['brainLearning'], queryFn: () => api.brainLearning() })
}

export function useProposals() {
  return useQuery({ queryKey: ['brainProposals'], queryFn: api.brainProposals })
}
