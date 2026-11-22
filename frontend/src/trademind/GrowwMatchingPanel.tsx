// Owner only: Groww holdings the app could not tie to a stock yet. Each row shows the ISIN and the Groww symbol; the
// owner picks the stock (or confirms the suggestions). Bookkeeping only; nothing here places an order.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { GrowwMatchItem, Instrument } from '../api/types'
import { refusalText } from './trackerRules'

export const GROWW_MATCH_KEY = ['growwMatching']
const TRACKER_KEY = ['myWatchlistTracker']

/** Tie one Groww holding (by ISIN) to the chosen search hit: the request carries the hit's instrument id. */
export const pickStock = (isin: string, hit: Pick<Instrument, 'id'>) => api.growwMatch(isin, hit.id)

/** Accept the stock Groww's name was matched to: posts the suggested instrument id. A row with no suggestion
 *  (or one the server could not point at a stock) posts nothing. */
export const acceptSuggestion = (row: GrowwMatchItem) =>
  row.match_state === 'suggested' && row.suggested_instrument_id != null
    ? api.growwMatch(row.isin, row.suggested_instrument_id)
    : Promise.resolve(null)

function Picker({ isin, onDone, onError }: { isin: string; onDone: () => void; onError: (m: string) => void }) {
  const [q, setQ] = useState('')
  const hits = useQuery({
    queryKey: ['growwPick', q],
    queryFn: () => api.instruments(q.trim(), 6),
    enabled: q.trim().length >= 2,
    staleTime: 60_000,
  })
  const pick = useMutation({
    mutationFn: (i: Instrument) => pickStock(isin, i),
    onSuccess: onDone,
    onError: (e) => onError(refusalText(e)),
  })
  return (
    <div className="gt-gpick">
      <input
        type="text"
        className="gt-cell"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search the stock"
        aria-label={`Find the stock for ${isin}`}
      />
      {(hits.data ?? []).map((i) => (
        <button key={i.id} type="button" className="gt-ghost" disabled={pick.isPending} onClick={() => pick.mutate(i)}>
          {i.tradingsymbol}
          {i.name ? ` · ${i.name}` : ''}
        </button>
      ))}
    </div>
  )
}

export function GrowwMatchingPanel() {
  const client = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const q = useQuery({ queryKey: GROWW_MATCH_KEY, queryFn: api.growwMatching, retry: false, staleTime: 30_000 })
  const reload = () => {
    setError(null)
    void client.invalidateQueries({ queryKey: GROWW_MATCH_KEY })
    void client.invalidateQueries({ queryKey: TRACKER_KEY })
  }
  const all = useMutation({ mutationFn: api.growwConfirmAll, onSuccess: reload, onError: (e) => setError(refusalText(e)) })
  const accept = useMutation({ mutationFn: acceptSuggestion, onSuccess: reload, onError: (e) => setError(refusalText(e)) })
  const items: GrowwMatchItem[] = q.data?.items ?? []
  if (q.isError && items.length === 0) {
    return (
      <p className="tm-neg tmn-small" role="alert" data-testid="groww-matching-error">
        The Groww holdings that need matching could not be loaded: {refusalText(q.error)}.
      </p>
    )
  }
  if (items.length === 0) return null
  const hasSuggestions = items.some((i) => i.match_state === 'suggested')
  return (
    <section className="tmn-card gt-gmatch" data-testid="groww-matching" aria-label="Needs matching">
      <h3>Needs matching</h3>
      <p className="tm-dim tmn-small">
        These Groww holdings are not tied to a stock yet, so they are not followed. Pick the right stock for each.
      </p>
      {hasSuggestions && (
        <button type="button" className="tmn-w2-primary" disabled={all.isPending} onClick={() => all.mutate()}>
          {all.isPending ? 'Confirming…' : 'Confirm all suggestions'}
        </button>
      )}
      {items.map((i) => (
        <div key={i.isin} className="gt-gmatch-row" data-isin={i.isin}>
          <div>
            <b>{i.trading_symbol}</b> <span className="tm-dim num">{i.isin}</span>
            <div className="tm-dim tmn-small">
              {i.quantity.toLocaleString('en-IN')} shares at ₹{i.average_price.toLocaleString('en-IN')}
              {i.match_state === 'suggested' && i.suggested_symbol ? ` · Suggested: ${i.suggested_symbol}` : ''}
            </div>
          </div>
          <div className="gt-gpick">
            {i.match_state === 'suggested' && i.suggested_symbol && i.suggested_instrument_id != null && (
              <button type="button" className="tmn-w2-primary" disabled={accept.isPending} onClick={() => accept.mutate(i)}>
                Use {i.suggested_symbol}
              </button>
            )}
            <Picker isin={i.isin} onDone={reload} onError={setError} />
          </div>
        </div>
      ))}
      {error && (
        <p className="tm-neg tmn-small" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
