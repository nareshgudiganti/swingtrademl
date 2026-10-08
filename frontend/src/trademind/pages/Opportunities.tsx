import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainDecision, IdeaWord } from '../../api/types'
import type { Action } from '../types'
import { finalWord, ideasFrom, useLatestRun } from '../live'
import { wordTone } from '../vocab'
import { CapFlag, useSymbolCaps } from '../cap'
import { ActionPill, BrainGate, Card, CheckItem, Icon, GlowArea, Ring, Seg, StockLogo, inr } from '../ui'

type Filter = 'ALL' | IdeaWord

function moneyOrDash(n: number | null): string {
  return n == null ? '—' : `₹${inr(n)}`
}

function entryPrice(d: BrainDecision): string {
  if (d.entry_low != null && d.entry_high != null && d.entry_low !== d.entry_high) {
    return `₹${inr(d.entry_low)} – ₹${inr(d.entry_high)}`
  }
  return moneyOrDash(d.entry_low ?? d.entry_high)
}

export default function Opportunities() {
  return (
    <BrainGate>
      <OpportunitiesBody />
    </BrainGate>
  )
}

function OpportunitiesBody() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const latest = useLatestRun()
  const [filter, setFilter] = useState<Filter>('ALL')
  const [query, setQuery] = useState('')
  const [buying, setBuying] = useState<string | null>(null)
  const [qty, setQty] = useState('1')
  const caps = useSymbolCaps()

  const buy = useMutation({
    mutationFn: (symbol: string) =>
      api.testerPaperBuy({
        symbol,
        quantity: Number(qty),
        cap_tier: caps.get(symbol.toUpperCase()) ?? 'large',
      }),
    onSuccess: () => {
      setBuying(null)
      queryClient.invalidateQueries({ queryKey: ['testerPositions'] })
      queryClient.invalidateQueries({ queryKey: ['testerSummary'] })
    },
  })

  const run = latest.data!
  const ideas = ideasFrom(run)
  const count = (w: IdeaWord) => ideas.filter((i) => finalWord(i) === w).length

  const rows = ideas.filter(
    (i) =>
      (filter === 'ALL' || finalWord(i) === filter) &&
      (query === '' || i.symbol.toLowerCase().includes(query.toLowerCase())),
  )

  // Featured = top TRADE if there is one, otherwise top WATCH. ideasFrom
  // already sorts TRADE/WATCH first by confidence, so the first match wins.
  const featured = ideas.find((i) => finalWord(i) === 'TRADE') ?? ideas.find((i) => finalWord(i) === 'WATCH')

  return (
    <div className="tm-page tm-grid">
      <Card glow>
        <div className="tm-toolbar">
          <Seg<Filter>
            active={filter}
            onChange={setFilter}
            options={[
              { id: 'ALL', label: `All (${ideas.length})` },
              { id: 'TRADE', label: `Trade (${count('TRADE')})` },
              { id: 'WATCH', label: `Watch (${count('WATCH')})` },
              { id: 'WAIT', label: `Wait (${count('WAIT')})` },
              { id: 'AVOID', label: `Avoid (${count('AVOID')})` },
            ]}
          />
          <span className="tm-spacer" />
          <span className="tm-flex" style={{ gap: 0, position: 'relative' }}>
            <span style={{ position: 'absolute', left: 8, color: 'var(--tm-faint)', display: 'flex' }}>
              <Icon.Search size={13} />
            </span>
            <input
              className="tm-input"
              style={{ paddingLeft: 26 }}
              placeholder="Search stocks..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </span>
        </div>

        <div className="tm-table-wrap">
          <table className="tm-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th>Size</th>
                <th>Decision</th>
                <th className="tm-right" title="A ranking, not a chance">
                  Model score
                </th>
                <th>Entry</th>
                <th>Target</th>
                <th>SL</th>
                <th>Why</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <Fragment key={i.id}>
                  <tr
                    className="tm-clickable"
                    onClick={() => navigate(`/trademind/stock/${encodeURIComponent(i.symbol)}`)}
                  >
                    <td className="tm-strong">{i.symbol}</td>
                    <td>
                      <CapFlag tier={caps.get(i.symbol.toUpperCase())} />
                    </td>
                    <td>
                      <ActionPill action={finalWord(i) as Action} />
                    </td>
                    <td className="tm-right tm-num">{i.confidence != null ? Math.round(i.confidence * 100) : '—'}</td>
                    <td className="tm-dim">{entryPrice(i)}</td>
                    <td className="tm-dim">{moneyOrDash(i.target)}</td>
                    <td className="tm-dim">{moneyOrDash(i.stop)}</td>
                    <td className="tm-dim tm-wrap">{i.reasons[0] ?? '—'}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="tm-btn"
                        onClick={() => {
                          setBuying(buying === i.symbol ? null : i.symbol)
                          setQty('1')
                        }}
                      >
                        {buying === i.symbol ? 'Close' : 'Buy'}
                      </button>
                    </td>
                  </tr>
                  {buying === i.symbol && (
                    <tr key={`${i.id}-buy`}>
                      <td colSpan={9} onClick={(e) => e.stopPropagation()}>
                        <form
                          className="tm-flex tm-wrap"
                          style={{ gap: '0.5rem', alignItems: 'center', padding: '0.35rem 0' }}
                          onSubmit={(e) => {
                            e.preventDefault()
                            buy.mutate(i.symbol)
                          }}
                        >
                          <span className="tm-strong">Paper buy {i.symbol}</span>
                          <input
                            className="tm-input"
                            type="number"
                            min={1}
                            value={qty}
                            onChange={(e) => setQty(e.target.value)}
                            aria-label="Quantity"
                            style={{ width: 90 }}
                          />
                          <button className="tm-btn" type="submit" disabled={!Number(qty) || buy.isPending}>
                            {buy.isPending ? 'Buying…' : 'Paper buy'}
                          </button>
                          {buy.isError && buying === i.symbol && (
                            <span className="tm-neg">{(buy.error as Error).message}</span>
                          )}
                        </form>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="tm-dim" style={{ textAlign: 'center', padding: '1.5rem' }}>
                    No stocks match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {buy.isSuccess && (
          <p className="tm-pos" style={{ marginTop: '0.6rem' }}>
            Paper buy placed for {String(buy.variables)}. It is under Portfolio → Testing.
          </p>
        )}
      </Card>

      {/* Featured idea: the top TRADE, or the top WATCH if there is no TRADE */}
      {featured ? (
        <FeaturedCard decision={featured} />
      ) : (
        <Card title="Featured Idea">
          <p className="tm-dim">No TRADE or WATCH idea right now.</p>
        </Card>
      )}
    </div>
  )
}

// The heading says what the brain actually decided — a WATCH idea the risk
// check refused is not one TradeMind "likes".
const WHY_HEADING: Record<string, string> = {
  TRADE: 'Why TradeMind likes this',
  WATCH: 'Why TradeMind is watching this',
  WAIT: 'Why TradeMind is waiting',
  AVOID: 'Why TradeMind avoids this',
}

function FeaturedCard({ decision }: { decision: BrainDecision }) {
  const caps = useSymbolCaps()
  const candles = useQuery({
    queryKey: ['candles', decision.symbol, 30],
    queryFn: () => api.candles(decision.symbol, 30),
  })
  const points = (candles.data ?? []).map((c) => ({ t: c.ts.slice(5, 10), v: c.close }))

  return (
    <Card glow className="tm-feature">
      <div className="tm-feature-logo">
        <StockLogo symbol={decision.symbol} />
      </div>
      <div className="tm-feature-name">
        <div className="tm-strong" style={{ fontSize: '0.95rem' }}>
          {decision.symbol}
          <CapFlag tier={caps.get(decision.symbol.toUpperCase())} gap />
        </div>
        <div className="tm-pos" style={{ fontSize: '0.72rem', marginTop: 4 }}>
          <ActionPill action={finalWord(decision) as Action} />
        </div>
      </div>
      <div className="tm-flex tm-feature-viz">
        <Ring
          value={decision.confidence != null ? Math.round(decision.confidence * 100) : 0}
          empty={decision.confidence == null}
          size={84}
          stroke={8}
          center={
            <>
              <span className="tm-ring-value" style={{ fontSize: 20 }}>
                {decision.confidence != null ? Math.round(decision.confidence * 100) : '—'}
              </span>
              <span className="tm-ring-label">Model score</span>
            </>
          }
        />
        <div style={{ flex: 1, minWidth: 120 }}>
          {candles.isLoading && <p className="tm-dim">Loading price…</p>}
          {candles.isError && <p className="tm-dim">Price history not available.</p>}
          {points.length > 0 && <GlowArea data={points} height={70} formatter={(v) => `₹${inr(v, 0)}`} />}
        </div>
      </div>
      <div className="tm-feature-why">
        {(decision.entry_low != null || decision.target != null || decision.stop != null) && (
          <p className="tm-note" style={{ marginBottom: '0.5rem' }}>
            Entry {entryPrice(decision)} · target {moneyOrDash(decision.target)} · SL {moneyOrDash(decision.stop)}
          </p>
        )}
        <div className="tm-strong" style={{ marginBottom: 2 }}>
          {WHY_HEADING[finalWord(decision)] ?? 'Why TradeMind decided this'}
        </div>
        {decision.reasons.map((w, idx) => (
          <CheckItem key={idx} tone={wordTone(finalWord(decision))}>
            {w}
          </CheckItem>
        ))}
      </div>
      <Link className="tm-btn tm-feature-btn" to={`/trademind/stock/${encodeURIComponent(decision.symbol)}`}>
        View Details
      </Link>
    </Card>
  )
}
