import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainDecision } from '../../api/types'
import { finalWord, ideasFrom, useLatestRun } from '../live'
import type { Action } from '../types'
import { ActionPill, BrainGate, Card, inr } from '../ui'

type CapTier = 'large' | 'midcap' | 'smallcap'

function entryZone(d: BrainDecision): string {
  if (d.entry_low == null || d.entry_high == null) return '—'
  return `₹${inr(d.entry_low)} – ₹${inr(d.entry_high)}`
}

export default function Watchlist() {
  return (
    <BrainGate>
      <WatchlistBody />
    </BrainGate>
  )
}

function WatchlistBody() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const latest = useLatestRun()
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })
  const [buying, setBuying] = useState<string | null>(null)
  const [qty, setQty] = useState('1')
  const [capTier, setCapTier] = useState<CapTier>('large')

  const ideas = latest.data ? ideasFrom(latest.data) : []
  const bySymbol = new Map(ideas.map((d) => [d.symbol.toUpperCase(), d]))
  const symbols = watchlist.data ?? []

  const buy = useMutation({
    mutationFn: (symbol: string) =>
      api.testerPaperBuy({ symbol, quantity: Number(qty), cap_tier: capTier }),
    onSuccess: () => {
      setBuying(null)
      queryClient.invalidateQueries({ queryKey: ['testerPositions'] })
      queryClient.invalidateQueries({ queryKey: ['testerSummary'] })
    },
  })

  return (
    <div className="tm-page tm-grid">
      <Card glow title="Watchlist" sub="Buy only from here. The paper position shows under Portfolio → Testing.">
        {watchlist.isLoading && <p className="tm-dim">Loading…</p>}
        {watchlist.isError && <p className="tm-dim">Could not load the watchlist.</p>}
        {symbols.length === 0 && !watchlist.isLoading && (
          <p className="tm-dim">No symbols on the watchlist yet. Add them in Settings.</p>
        )}
        {buy.isError && <p className="tm-dim">{(buy.error as Error).message}</p>}
        {symbols.length > 0 && (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th>Decision</th>
                  <th className="tm-right">Model score</th>
                  <th>Entry zone</th>
                  <th>Target</th>
                  <th>Stop</th>
                  <th>Why</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {symbols.map((inst) => {
                  const d = bySymbol.get(inst.tradingsymbol.toUpperCase())
                  const word = d ? finalWord(d) : null
                  return (
                    <tr
                      key={inst.tradingsymbol}
                      className="tm-clickable"
                      onClick={() => navigate(`/trademind/stock/${encodeURIComponent(inst.tradingsymbol)}`)}
                    >
                      <td className="tm-strong">{inst.tradingsymbol}</td>
                      <td>{word ? <ActionPill action={word as Action} /> : <span className="tm-dim">—</span>}</td>
                      <td className="tm-right tm-num">
                        {d?.confidence != null ? Math.round(d.confidence * 100) : '—'}
                      </td>
                      <td className="tm-dim">{d && word === 'TRADE' ? entryZone(d) : '—'}</td>
                      <td className="tm-dim">{d && word === 'TRADE' && d.target != null ? `₹${inr(d.target)}` : '—'}</td>
                      <td className="tm-dim">{d && word === 'TRADE' && d.stop != null ? `₹${inr(d.stop)}` : '—'}</td>
                      <td className="tm-dim tm-wrap">{d?.reasons[0] ?? '—'}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="tm-btn"
                          onClick={() => {
                            setBuying(inst.tradingsymbol)
                            setQty('1')
                          }}
                        >
                          Buy
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {buying && (
          <form
            className="tm-callout"
            style={{ marginTop: '0.8rem' }}
            onSubmit={(e) => {
              e.preventDefault()
              buy.mutate(buying)
            }}
          >
            <div className="tm-strong" style={{ marginBottom: '0.4rem' }}>
              Paper buy {buying}
            </div>
            <div className="tm-flex tm-wrap" style={{ gap: '0.5rem' }}>
              <input
                className="tm-input"
                type="number"
                min={1}
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                aria-label="Quantity"
              />
              <select className="tm-input" value={capTier} onChange={(e) => setCapTier(e.target.value as CapTier)} aria-label="Company size">
                <option value="large">Large</option>
                <option value="midcap">Mid</option>
                <option value="smallcap">Small</option>
              </select>
              <button className="tm-btn" type="submit" disabled={!Number(qty) || buy.isPending}>
                {buy.isPending ? 'Buying…' : 'Paper buy'}
              </button>
              <button className="tm-btn" type="button" onClick={() => setBuying(null)}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </Card>
    </div>
  )
}
