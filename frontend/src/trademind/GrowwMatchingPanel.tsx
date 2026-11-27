// Owner only: Groww holdings the app could not tie to a stock yet. Each row shows the ISIN and the Groww symbol; the
// owner picks the stock (or confirms the suggestions). Bookkeeping only; nothing here places an order.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { GrowwMatchItem, Instrument } from '../api/types'
import { refusalText } from './trackerRules'

export const GROWW_MATCH_KEY = ['growwMatching']
const TRACKER_KEY = ['myWatchlistTracker']

/** A holding can only be matched through its ISIN: without one there is nothing to put in the request path. */
const hasIsin = (isin: string | null | undefined): isin is string => !!isin && isin.trim() !== ''

const unknownOr = (value: number | null, show: (n: number) => string): string => (value == null ? 'unknown' : show(value))

/** Tie one Groww holding (by ISIN) to the chosen search hit: the request carries the hit's instrument id. */
export const pickStock = (isin: string, hit: Pick<Instrument, 'id'>) =>
  hasIsin(isin) ? api.growwMatch(isin, hit.id) : Promise.resolve(null)

/** Accept the stock Groww's name was matched to: posts the suggested instrument id. A row with no suggestion
 *  (or one the server could not point at a stock) posts nothing. */
export const acceptSuggestion = (row: GrowwMatchItem) =>
  row.match_state === 'suggested' && row.suggested_instrument_id != null && hasIsin(row.isin)
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
  const listed: GrowwMatchItem[] = q.data?.items ?? []
  // Rows with no ISIN are counted, never listed: the server already leaves them out, a blank one is caught here.
  const items = listed.filter((i) => hasIsin(i.isin))
  const withoutIsin = (q.data?.without_isin ?? 0) + (listed.length - items.length)
  if (q.isError && items.length === 0) {
    return (
      <p className="tm-neg tmn-small" role="alert" data-testid="groww-matching-error">
        The Groww holdings that need matching could not be loaded: {refusalText(q.error)}.
      </p>
    )
  }
  const noIsinLine = withoutIsin > 0 && (
    <p className="tm-dim tmn-small" data-testid="groww-no-isin">
      {withoutIsin === 1
        ? '1 Groww holding cannot be matched because Groww gave no ISIN for it.'
        : `${withoutIsin} Groww holdings cannot be matched because Groww gave no ISIN for them.`}
    </p>
  )
  if (items.length === 0) return noIsinLine || null
  const hasSuggestions = items.some((i) => i.match_state === 'suggested')
  return (
    <>
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
            <b>{i.trading_symbol ?? 'unknown'}</b> <span className="tm-dim num">{i.isin}</span>
            <div className="tm-dim tmn-small">
              {unknownOr(i.quantity, (n) => n.toLocaleString('en-IN'))} shares at{' '}
              {unknownOr(i.average_price, (n) => `₹${n.toLocaleString('en-IN')}`)}{i.average_price == null ? ' price' : ''}
              {i.match_state === 'suggested' && i.suggested_symbol ? ` · Suggested: ${i.suggested_symbol}` : ''}
            </div>
            {i.conflict_symbol && (
              <div className="tm-neg tmn-small" data-testid="groww-conflict">
                Another Groww holding is also matched to {i.conflict_symbol}, so neither is followed. Pick the right stock for this one.
              </div>
            )}
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
    {noIsinLine}
    </>
  )
}
