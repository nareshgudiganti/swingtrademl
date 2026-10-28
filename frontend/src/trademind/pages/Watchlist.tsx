import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainDecision } from '../../api/types'
import { finalWord, ideasFrom, useLatestRun } from '../live'
import type { Action } from '../types'
import { CapFlag, useSymbolCaps } from '../cap'
import { SortTh, useSort } from '../sort'
import StockLink from '../StockLink'
import { ActionPill, BrainGate, Card, inr } from '../ui'
import { QueryNotice } from '../PageState'
import { SCORE_HINT, scoreLabel, withoutScorePercent } from '../scoreText'

function entryZone(d: BrainDecision): string {
  if (d.entry_low != null && d.entry_high != null && d.entry_low !== d.entry_high) {
    return `₹${inr(d.entry_low)} – ₹${inr(d.entry_high)}`
  }
  const one = d.entry_low ?? d.entry_high
  return one == null ? '—' : `₹${inr(one)}`
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
  const latest = useLatestRun()
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })
  const caps = useSymbolCaps()

  const ideas = latest.data ? ideasFrom(latest.data) : []
  const bySymbol = new Map(ideas.map((d) => [d.symbol.toUpperCase(), d]))
  const dayScores = ideas.map((d) => d.confidence)
  const { sorted: symbols, sorter } = useSort(watchlist.data ?? [], {
    stock: (i: { tradingsymbol: string }) => i.tradingsymbol,
    decision: (i: { tradingsymbol: string }) => {
      const d = bySymbol.get(i.tradingsymbol.toUpperCase())
      return d ? finalWord(d) : null
    },
    score: (i: { tradingsymbol: string }) => bySymbol.get(i.tradingsymbol.toUpperCase())?.confidence,
    target: (i: { tradingsymbol: string }) => bySymbol.get(i.tradingsymbol.toUpperCase())?.target,
    stop: (i: { tradingsymbol: string }) => bySymbol.get(i.tradingsymbol.toUpperCase())?.stop,
  }, { key: null }, { stock: 'asc', decision: 'asc' })

  return (
    <div className="tm-page tm-grid">
      <Card glow title="Watchlist" sub="What the brain says about each stock you follow. Practice buys are on Portfolio → Manual test.">
        <QueryNotice q={watchlist} what="the watchlist" />
        {symbols.length === 0 && watchlist.data !== undefined && (
          <p className="tm-dim">No symbols on the watchlist yet. Add them in Settings.</p>
        )}
        {symbols.length > 0 && (
          <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
            <table className="tm-table">
              <thead>
                <tr>
                  <SortTh sorter={sorter} k="stock">Stock</SortTh>
                  <th>Size</th>
                  <SortTh sorter={sorter} k="decision">Decision</SortTh>
                  <SortTh sorter={sorter} k="score" right title={SCORE_HINT}>
                    Model score rank
                  </SortTh>
                  <th>Entry zone</th>
                  <SortTh sorter={sorter} k="target">Target</SortTh>
                  <SortTh sorter={sorter} k="stop">Stop</SortTh>
                  <th>Why</th>
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
                      <td><StockLink symbol={inst.tradingsymbol} withScore={false} /></td>
                      <td>
                        <CapFlag tier={caps.get(inst.tradingsymbol.toUpperCase())} />
                      </td>
                      <td>{word ? <ActionPill action={word as Action} /> : <span className="tm-dim">—</span>}</td>
                      <td className="tm-right tm-num">
                        {d ? scoreLabel(d.confidence, dayScores) : '—'}
                      </td>
                      <td className="tm-dim">{d ? entryZone(d) : '—'}</td>
                      <td className="tm-dim">{d?.target != null ? `₹${inr(d.target)}` : '—'}</td>
                      <td className="tm-dim">{d?.stop != null ? `₹${inr(d.stop)}` : '—'}</td>
                      <td className="tm-dim tm-wrap">{d?.reasons[0] ? withoutScorePercent(d.reasons[0]) : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
