// tr5: a small badge on a thin strip under the top bar (the bar itself is full) that says whether REAL Zerodha orders from My Holdings are
// switched on. "Real orders: ON" is red and stays visible on a phone; "Real orders: OFF" is grey.
//
// Only the real account's owner sees it (GET /portfolio/real/orders-status is refused for everyone else, and the
// caller only mounts it for canSeeRealAccount). While the answer is not in, or if the request fails, nothing is
// drawn: a wrong "OFF" would be worse than no badge.

import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { RealOrdersStatus } from '../api/types'

export function RealOrdersBadgeView({ status }: { status: RealOrdersStatus | undefined }) {
  if (!status) return null
  const on = status.enabled === true
  return (
    <div className="tm-realorders-strip">
      <span
        className={`tm-realorders-chip ${on ? 'tm-realorders-on' : 'tm-realorders-off'}`}
        data-testid="real-orders-badge"
        data-on={on ? 'true' : 'false'}
        title={
          on
            ? 'Real orders are ON: buying or selling from My Holdings sends a real order to Zerodha with real money.'
            : 'Real orders are OFF: My Holdings cannot send orders to Zerodha. The bot itself always uses practice money.'
        }
      >
        {on ? 'Real orders: ON' : 'Real orders: OFF'}
      </span>
    </div>
  )
}

/** Owner's top bar: asks the server; shows nothing until it answers, and nothing if it refuses or fails. */
export default function RealOrdersBadge({ enabled = true }: { enabled?: boolean }) {
  // Same key as My Holdings, so turning the switch there updates this badge at once.
  const q = useQuery({
    queryKey: ['realOrdersStatus'],
    queryFn: api.realOrdersStatus,
    enabled,
    retry: false,
    refetchInterval: 60_000,
  })
  if (!enabled || q.isError) return null
  return <RealOrdersBadgeView status={q.data} />
}
