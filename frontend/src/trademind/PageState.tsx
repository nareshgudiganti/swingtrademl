// One shared way to draw "not ready yet" on a TradeMind screen: loading, offline, signed out, not allowed,
// failed (with a "Try again" button), or empty WITH the reason the caller passes. The rules for which state
// applies live in stateRules.ts; this file only draws them.
//
//   <QueryState q={positions} what="your positions" isEmpty={(d) => d.length === 0}
//               empty="The bot holds no shares right now.">
//     {(rows) => <Table rows={rows} />}
//   </QueryState>
//
// When a refetch fails but data was loaded before, the data stays on screen with a small StaleNotice above it.

import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'

import { browserOnline, errorText, pickState, staleSince, staleText, type QueryLike, type StateKind } from './stateRules'

// ---------------------------------------------------------------- online --

function subscribeOnline(cb: () => void) {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener('online', cb)
  window.addEventListener('offline', cb)
  return () => {
    window.removeEventListener('online', cb)
    window.removeEventListener('offline', cb)
  }
}

/** True while the browser says it is online; updates on the online/offline events. */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribeOnline, browserOnline, () => true)
}

/** A thin strip under the menu while the phone or computer has no internet. */
export function OfflineBanner() {
  const online = useOnline()
  if (online) return null
  return (
    <div className="tm-offline" role="status" data-testid="offline-banner">
      You're offline. You're seeing the last data that loaded; it will refresh when you're back online.
    </div>
  )
}

// ----------------------------------------------------------------- stale --

/** Re-render once a minute so "from 15:42" changes to "18 Oct, 15:42" after midnight. */
function useMinuteTick() {
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000)
    return () => clearInterval(id)
  }, [])
}

/** "Showing data from 15:42 — can't reach the server right now." Renders nothing when the data is fresh. */
export function StaleNotice({ q }: { q: QueryLike }) {
  const online = useOnline()
  useMinuteTick()
  const since = staleSince(q, online)
  if (since == null) return null
  return (
    <p className="tm-stale" role="status" data-testid="stale-notice">
      {staleText(since, online)}
    </p>
  )
}

// ----------------------------------------------------------------- states --

const SIGN_IN_AGAIN = () => window.location.assign('/')

/**
 * Draws one non-ready state. `reason` is the empty state's explanation and should say WHY it is empty when the
 * API told us; `what` names the thing being loaded ("your positions").
 */
export function PageState({
  kind,
  what = 'this',
  reason,
  error,
  onRetry,
  title,
}: {
  kind: Exclude<StateKind, 'ready'>
  what?: string
  reason?: ReactNode
  error?: unknown
  onRetry?: () => unknown
  title?: string
}) {
  const online = useOnline()
  switch (kind) {
    case 'loading':
      return (
        <p className="tm-dim tm-state" data-state="loading" aria-busy="true">
          Loading {what}…
        </p>
      )
    case 'offline':
      return (
        <p className="tm-dim tm-state" data-state="offline">
          You're offline, so {what} has not loaded yet. It will load when you're back online.
        </p>
      )
    case 'signed-out':
      return (
        <div className="tm-state tm-state-box" data-state="signed-out">
          <p className="tm-strong">You're signed out.</p>
          <p className="tm-dim">Sign in again to see {what}.</p>
          <button type="button" className="tm-btn" onClick={SIGN_IN_AGAIN}>
            Sign in
          </button>
        </div>
      )
    case 'forbidden':
      return (
        <div className="tm-state tm-state-box" data-state="forbidden">
          <p className="tm-strong">Not available on your account.</p>
          <p className="tm-dim">Your account does not include {what}. Ask the owner if you think it should.</p>
        </div>
      )
    case 'not-found':
      return (
        <div className="tm-state tm-state-box" data-state="not-found">
          <p className="tm-dim">{reason ?? `There is nothing stored for ${what} yet.`}</p>
        </div>
      )
    case 'error':
      return (
        <div className="tm-state tm-state-box tm-state-error" data-state="error" role="alert">
          {title && <p className="tm-strong">{title}</p>}
          <p className="tm-dim">{errorText(error, what, online)}</p>
          {onRetry && (
            <button type="button" className="tm-btn tm-btn-ghost" onClick={() => void onRetry()}>
              Try again
            </button>
          )}
        </div>
      )
    case 'empty':
      return (
        <p className="tm-dim tm-state" data-state="empty">
          {reason ?? `Nothing to show for ${what}.`}
        </p>
      )
  }
}

/**
 * The usual case: one query. Renders the right state, or the children with the data (plus a stale notice when
 * the last refetch failed). `isEmpty` decides "loaded but nothing in it"; `empty` is the reason shown then.
 * `notFound` (a 404) is treated as empty with that reason when given, e.g. "No report stored yet".
 */
export function QueryState<T>({
  q,
  what,
  isEmpty,
  empty,
  notFound,
  errorTitle,
  children,
}: {
  q: QueryLike & { data?: T; refetch?: () => unknown }
  what: string
  isEmpty?: (data: T) => boolean
  empty?: ReactNode
  notFound?: ReactNode
  errorTitle?: string
  children: (data: T) => ReactNode
}) {
  const kind = pickState(q, q.data !== undefined && isEmpty ? isEmpty(q.data as T) : false)
  if (kind === 'ready') {
    return (
      <>
        <StaleNotice q={q} />
        {children(q.data as T)}
      </>
    )
  }
  if (kind === 'empty') {
    return (
      <>
        <StaleNotice q={q} />
        <PageState kind="empty" what={what} reason={empty} />
      </>
    )
  }
  if (kind === 'not-found' && notFound) return <PageState kind="empty" what={what} reason={notFound} />
  return <PageState kind={kind} what={what} error={q.error} onRetry={q.refetch} title={errorTitle} />
}

/**
 * For screens that already draw `{q.data && …}` themselves: renders the loading / offline / error (with
 * "Try again") / signed-out state while there is no data, and the stale notice once there is. Put it just
 * above the existing data block.
 */
export function QueryNotice({
  q,
  what,
  notFound,
}: {
  q: QueryLike & { refetch?: () => unknown }
  what: string
  notFound?: ReactNode
}) {
  const kind = pickState(q)
  if (kind === 'ready' || kind === 'empty') return <StaleNotice q={q} />
  if (kind === 'not-found' && notFound) return <PageState kind="empty" what={what} reason={notFound} />
  return <PageState kind={kind} what={what} error={q.error} onRetry={q.refetch} />
}
