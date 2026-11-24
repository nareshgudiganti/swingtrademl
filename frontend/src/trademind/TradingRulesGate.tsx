import { useQuery } from '@tanstack/react-query'
import { Component, type ReactNode } from 'react'

import { ApiError, api, clearToken, getToken } from '../api/client'
import { Loading } from '../components/Loading'
import { setTradingRules } from './tradingRules'

/** Owner pages that show no trading number (the people and plans managers). When the numbers cannot be loaded
 *  these still open, so the owner can reach them; every other page waits for the numbers. */
export const PAGES_WITHOUT_RULE_NUMBERS = ['/admin', '/plans', '/trademind/people', '/trademind/plans']

export function showsNoRuleNumbers(pathname: string): boolean {
  return PAGES_WITHOUT_RULE_NUMBERS.some((p) => pathname === p || pathname.startsWith(`${p}/`))
}

/** Loads the trading numbers once after sign-in. Until they are here the app shows nothing that uses them, and
 *  if they cannot be loaded it says so plainly: a screen never shows a guessed number. Signed out: no request.
 *  The numbers are stored when the request finishes, not while rendering. */
export default function TradingRulesGate({ children }: { children: ReactNode }) {
  const signedIn = !!getToken()
  const rules = useQuery({
    queryKey: ['tradingRules'],
    queryFn: async () => {
      const loaded = await api.tradingRules()
      setTradingRules(loaded) // before any screen renders from this result
      return loaded
    },
    enabled: signedIn,
    staleTime: Infinity,
    retry: 1,
  })
  if (!signedIn) return <>{children}</>
  // An expired sign-in: the request cleared the token, so let the app fall back to the sign-in screen.
  if (rules.error instanceof ApiError && rules.error.status === 401) return <>{children}</>
  if (rules.data) return <>{children}</>
  if (rules.isError) {
    const retry = () => void rules.refetch()
    if (showsNoRuleNumbers(window.location.pathname)) {
      // A page with no rule number can open; if it turns out to need one, it says so instead of crashing.
      return <Guard fallback={<RulesUnavailable onRetry={retry} />}>{children}</Guard>
    }
    return <RulesUnavailable onRetry={retry} />
  }
  return <Loading />
}

/** Falls back to the given screen if a child throws (for example a page that asks for a rule that did not load). */
class Guard extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

/** Shown instead of the app when the numbers cannot be loaded: nothing that uses them is rendered. */
export function RulesUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="card" role="alert" style={{ maxWidth: 480, margin: '2rem auto' }}>
      <h2 style={{ marginTop: 0 }}>The trading numbers are unavailable right now</h2>
      <p>Nothing is shown until they load, so you never see a wrong number. Check your connection and try again.</p>
      <button className="primary" onClick={onRetry}>
        Try again
      </button>{' '}
      <button
        onClick={() => {
          clearToken()
          window.location.assign('/')
        }}
      >
        Sign out
      </button>
    </div>
  )
}
