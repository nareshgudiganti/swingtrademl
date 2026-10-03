import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainDecision, IdeaWord } from '../../api/types'
import type { Action } from '../types'
import { finalWord, ideasFrom, useLatestRun } from '../live'
import { wordTone } from '../vocab'
import { ActionPill, BrainGate, Card, CheckItem, Icon, GlowArea, Ring, Seg, StockLogo, inr } from '../ui'

type Filter = 'ALL' | IdeaWord

function entryZone(d: BrainDecision): string {
  if (d.entry_low == null || d.entry_high == null) return '—'
  return `₹${inr(d.entry_low)} – ₹${inr(d.entry_high)}`
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
  const latest = useLatestRun()
  const [filter, setFilter] = useState<Filter>('ALL')
  const [query, setQuery] = useState('')

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
                <th>Decision</th>
                <th className="tm-right" title="A ranking, not a chance">
                  Model score
                </th>
                <th>Entry zone</th>
                <th>Target</th>
                <th>Stop</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr
                  key={i.id}
                  className="tm-clickable"
                  onClick={() => navigate(`/trademind/stock/${encodeURIComponent(i.symbol)}`)}
                >
                  <td className="tm-strong">{i.symbol}</td>
                  <td>
                    <ActionPill action={finalWord(i) as Action} />
                  </td>
                  <td className="tm-right tm-num">{i.confidence != null ? Math.round(i.confidence * 100) : '—'}</td>
                  <td className="tm-dim">{finalWord(i) === 'TRADE' ? entryZone(i) : '—'}</td>
                  <td className="tm-dim">{finalWord(i) === 'TRADE' && i.target != null ? `₹${inr(i.target)}` : '—'}</td>
                  <td className="tm-dim">{finalWord(i) === 'TRADE' && i.stop != null ? `₹${inr(i.stop)}` : '—'}</td>
                  <td className="tm-dim">{i.reasons[0] ?? '—'}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="tm-dim" style={{ textAlign: 'center', padding: '1.5rem' }}>
                    No stocks match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
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

function FeaturedCard({ decision }: { decision: BrainDecision }) {
  const candles = useQuery({
    queryKey: ['candles', decision.symbol, 30],
    queryFn: () => api.candles(decision.symbol, 30),
  })
  const points = (candles.data ?? []).map((c) => ({ t: c.ts.slice(5, 10), v: c.close }))

  return (
    <Card glow className="tm-feature">
      <StockLogo symbol={decision.symbol} />
      <div>
        <div className="tm-strong" style={{ fontSize: '0.95rem' }}>
          {decision.symbol}
        </div>
        <div className="tm-pos" style={{ fontSize: '0.72rem', marginTop: 4 }}>
          <ActionPill action={finalWord(decision) as Action} />
        </div>
      </div>
      <div className="tm-flex" style={{ minWidth: 0 }}>
        <Ring
          value={decision.confidence != null ? Math.round(decision.confidence * 100) : 0}
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
      <div>
        {finalWord(decision) === 'TRADE' && decision.entry_low != null && (
          <p className="tm-note" style={{ marginBottom: '0.5rem' }}>
            Buy around {entryZone(decision)} · target {decision.target != null ? `₹${inr(decision.target)}` : '—'} · stop{' '}
            {decision.stop != null ? `₹${inr(decision.stop)}` : '—'}
          </p>
        )}
        <div className="tm-strong" style={{ marginBottom: 2 }}>
          Why TradeMind {finalWord(decision) === 'AVOID' ? 'avoids' : 'likes'} this
        </div>
        {decision.reasons.map((w, idx) => (
          <CheckItem key={idx} tone={wordTone(finalWord(decision))}>
            {w}
          </CheckItem>
        ))}
      </div>
      <Link className="tm-btn" to={`/trademind/stock/${encodeURIComponent(decision.symbol)}`}>
        View Details
      </Link>
    </Card>
  )
}
