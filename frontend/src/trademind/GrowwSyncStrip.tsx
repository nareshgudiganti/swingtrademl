// Owner only: when Groww last synced, a Refresh button, and the banner for a sync that came back empty.
// The server sends `groww` only to the owner; without it nothing is drawn. Display and bookkeeping only.

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { GrowwStatus, GrowwSyncResult } from '../api/types'
import { GROWW_MATCH_KEY } from './GrowwMatchingPanel'
import { fmtDayMonth, fmtIstStamp, refusalText } from './trackerRules'

export { refusalText }

const TRACKER_KEY = ['myWatchlistTracker']

export type RefreshOutcome = { kind: 'done' | 'failed' | 'busy'; text: string }

/** Turn the result of a Refresh into what the owner reads. "Already refreshing" is neutral, not a failure. */
export async function runRefresh(sync: () => Promise<GrowwSyncResult>): Promise<RefreshOutcome> {
  try {
    const r = await sync()
    if (r.status === 'failed') return { kind: 'failed', text: 'Groww did not answer' }
    return { kind: 'done', text: `Done. ${r.holdings_count} ${r.holdings_count === 1 ? 'holding' : 'holdings'} from Groww.` }
  } catch (e) {
    const msg = e instanceof Error ? e.message : ''
    if (/already refreshing/i.test(msg)) return { kind: 'busy', text: 'Already refreshing. Give it a moment.' }
    return { kind: 'failed', text: refusalText(e) }
  }
}

/** Confirm that an empty Groww answer is true. Does nothing without a sync id. */
export function confirmEmptySync(groww: Pick<GrowwStatus, 'last_sync_id'>) {
  return groww.last_sync_id == null ? Promise.resolve(null) : api.growwConfirmEmpty(groww.last_sync_id)
}

export function GrowwSyncStrip({ groww, priceDate }: { groww: GrowwStatus; priceDate: string | null }) {
  const client = useQueryClient()
  const [done, setDone] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const reload = () => {
    void client.invalidateQueries({ queryKey: TRACKER_KEY })
    void client.invalidateQueries({ queryKey: GROWW_MATCH_KEY })
  }
  const [busy, setBusy] = useState<string | null>(null)
  const sync = useMutation({
    mutationFn: () => runRefresh(api.growwSync),
    onMutate: () => {
      setDone(null)
      setFailed(null)
      setBusy(null)
    },
    onSuccess: (o) => {
      if (o.kind === 'done') setDone(o.text)
      else if (o.kind === 'busy') setBusy(o.text)
      else setFailed(o.text)
      reload()
    },
  })
  const confirmEmpty = useMutation({
    mutationFn: () => confirmEmptySync(groww),
    onSuccess: reload,
    onError: (e) => setFailed(refusalText(e)),
  })

  const synced = fmtIstStamp(groww.last_success_at)
  const priced = fmtDayMonth(priceDate)
  const lastBad = groww.last_status === 'failed' || groww.last_status === 'partial'
  const showFail = failed !== null || lastBad
  const empty = groww.last_status === 'empty_unconfirmed' && groww.last_sync_id != null

  return (
    <section className="gt-gsync" data-testid="groww-strip" aria-label="Groww sync">
      <div className="gt-gsync-row">
        <span>
          {!groww.configured
            ? 'Groww sync is not set up yet.'
            : synced
              ? `Groww synced ${synced}${priced ? ` · prices from ${priced} close` : ''}`
              : 'Groww has not synced yet.'}
        </span>
        {groww.configured && (
          <button type="button" className="gt-ghost" disabled={sync.isPending} onClick={() => sync.mutate()} data-testid="groww-refresh">
            {sync.isPending ? 'Refreshing…' : 'Refresh'}
          </button>
        )}
        {busy && (
          <span className="tm-dim tmn-small" role="status" data-testid="groww-busy">
            {busy}
          </span>
        )}
        {done && (
          <span className="tm-pos tmn-small" role="status">
            {done}
          </span>
        )}
      </div>
      {showFail && (
        <p className="tm-neg tmn-small" role="alert" data-testid="groww-fail">
          {failed ?? 'The last refresh did not finish'} —{' '}
          {synced ? `showing holdings from ${synced}.` : 'no holdings have come from Groww yet.'}
        </p>
      )}
      {empty && (
        <div className="gt-gsync-empty" data-testid="groww-empty-banner">
          <span>Groww returned no holdings — do you hold nothing?</span>
          <button type="button" className="gt-ghost" disabled={confirmEmpty.isPending} onClick={() => confirmEmpty.mutate()}>
            Confirm
          </button>
        </div>
      )}
    </section>
  )
}
