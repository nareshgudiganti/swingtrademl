// Which state a part of a screen is in: still loading, offline, signed out, not allowed, failed, empty or
// ready. Pure functions (no React), so the rules can be tested and every screen picks its state the same way.
// The component that draws each state is PageState.tsx.
//
// The one rule that matters most: if we already have data, we show it. A refetch that fails (slow or no
// network) never replaces good data with an error; the screen keeps the data and adds a small "showing data
// from 15:42" notice instead (see staleSince / staleText).

import { ApiError } from '../api/client'

/** The parts of a react-query result these rules read. Any useQuery() result fits. */
export type QueryLike = {
  data?: unknown
  error?: unknown
  isError: boolean
  isPending: boolean
  /** 'paused' = react-query is waiting for the network to come back. */
  fetchStatus?: 'fetching' | 'paused' | 'idle'
  /** When the data now on screen was loaded (ms since epoch; 0 = never). */
  dataUpdatedAt?: number
}

export type StateKind = 'loading' | 'offline' | 'signed-out' | 'forbidden' | 'not-found' | 'error' | 'empty' | 'ready'

/** The HTTP status behind a failed request, or null for a network failure / anything else. */
export function errorStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null
}

/**
 * The state to draw. `isEmpty` is the caller's own test of the data it got ("no rows"); it is only used once
 * there is data. Data always wins over an error: a failed refetch keeps showing what was loaded before.
 */
export function pickState(q: QueryLike, isEmpty = false): StateKind {
  if (q.data !== undefined) return isEmpty ? 'empty' : 'ready'
  if (q.isError) {
    const status = errorStatus(q.error)
    if (status === 401) return 'signed-out'
    if (status === 403) return 'forbidden'
    if (status === 404) return 'not-found'
    return 'error'
  }
  if (q.isPending && q.fetchStatus === 'paused') return 'offline'
  return 'loading'
}

/** Is the browser online? Plain Node (tests, server render) has no navigator: treat it as online. */
export function browserOnline(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine !== false
}

/**
 * When the data on screen is older than it should be because we could not reach the server: the time it was
 * loaded, or null when the data is fresh (or there is none). Stale = the last refetch failed, the browser is
 * offline, or react-query paused a refetch waiting for the network.
 */
export function staleSince(q: QueryLike, online = browserOnline()): number | null {
  if (q.data === undefined || !q.dataUpdatedAt) return null
  if (q.isError || !online || q.fetchStatus === 'paused') return q.dataUpdatedAt
  return null
}

const IST = 'Asia/Kolkata'

/** "15:42" for a time today (India time), "18 Oct, 15:42" for an earlier day. */
export function clockText(ts: number, now = Date.now()): string {
  const day = (t: number) => new Date(t).toLocaleDateString('en-CA', { timeZone: IST })
  const time = new Date(ts).toLocaleTimeString('en-GB', { timeZone: IST, hour: '2-digit', minute: '2-digit', hour12: false })
  if (day(ts) === day(now)) return time
  const date = new Date(ts).toLocaleDateString('en-GB', { timeZone: IST, day: 'numeric', month: 'short' })
  return `${date}, ${time}`
}

/** The small notice over stale data, e.g. "Showing data from 15:42 — can't reach the server right now." */
export function staleText(ts: number, online = browserOnline(), now = Date.now()): string {
  const why = online ? "can't reach the server right now" : "you're offline"
  return `Showing data from ${clockText(ts, now)} — ${why}.`
}

/** A plain sentence for a failed load. `what` names the thing, e.g. "your positions". Never shows raw codes
 *  as the main message; the server's own words are added only when they are a readable sentence. */
export function errorText(error: unknown, what: string, online = browserOnline()): string {
  if (!online) return `You're offline, so ${what} could not load. It will load when you're back online.`
  const status = errorStatus(error)
  if (status === null) return `Could not reach the server to load ${what}. Check your internet and try again.`
  if (status >= 500) return `The server had a problem loading ${what}. Try again in a minute.`
  return `Could not load ${what}.`
}
