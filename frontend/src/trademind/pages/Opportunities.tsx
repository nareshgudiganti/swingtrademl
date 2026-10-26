import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainDecision, IdeaWord } from '../../api/types'
import { finalWord, ideasFrom, useLatestRun } from '../live'
import { CapFlag, useSymbolCaps } from '../cap'
import { BrainGate, Card, Icon, GlowArea, Seg, StockLogo, inr } from '../ui'
import { noTradeReason } from '../emptyReasons'
import LiveIdeaCard from '../beginner/LiveIdeaCard'
import { usePlan } from '../../lib/plan'
import { StrategySignals } from '../StrategySignals'

type Filter = 'ALL' | IdeaWord

export default function Opportunities() {
  return (
    <BrainGate>
      <OpportunitiesBody />
    </BrainGate>
  )
}

function OpportunitiesBody() {
  const latest = useLatestRun()
  const [filter, setFilter] = useState<Filter>('ALL')
  const [query, setQuery] = useState('')
  const caps = useSymbolCaps()
  // oa5: the version 1 per-strategy signals, read only. Their endpoints are open to no plan, so only accounts
  // that see the whole app (the owner, or a tester while plans are off) get the list.
  const { seesAll } = usePlan()

  const run = latest.data!
  const ideas = ideasFrom(run)
  const count = (w: IdeaWord) => ideas.filter((i) => finalWord(i) === w).length
  // Every idea score in the run, so each card can say "Rank 2 of 9 today" instead of a bare number.
  const dayScores = ideas.map((d) => d.confidence)

  const rows = ideas.filter(
    (i) =>
      (filter === 'ALL' || finalWord(i) === filter) &&
      (query === '' || i.symbol.toLowerCase().includes(query.toLowerCase())),
  )

  // Why there are no TRADE ideas today, from the run's own banner (null when there are some).
  const noTrade = noTradeReason(run.banner, ideas.length, count('TRADE'))
  const emptyText =
    ideas.length === 0 || (filter === 'TRADE' && noTrade) ? noTrade : 'No stocks match these filters.'

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

        {noTrade && ideas.length > 0 && (
          <p className="tm-note" data-testid="no-trade-reason" style={{ marginTop: 0 }}>
            {noTrade}
          </p>
        )}
        <div className="bx-cards" data-testid="idea-cards">
          {rows.map((i) => (
            <LiveIdeaCard
              key={i.id}
              decision={i}
              compact
              dayScores={dayScores}
              tags={<CapFlag tier={caps.get(i.symbol.toUpperCase())} />}
            />
          ))}
          {rows.length === 0 && (
            <p className="tm-dim" data-state="empty" style={{ textAlign: 'center', padding: '1.5rem' }}>
              {emptyText}
            </p>
          )}
        </div>
      </Card>

      {/* Featured idea: the top TRADE, or the top WATCH if there is no TRADE */}
      {featured ? (
        <FeaturedCard decision={featured} dayScores={dayScores} />
      ) : (
        <Card title="Featured Idea">
          <p className="tm-dim" data-state="empty">No TRADE or WATCH idea right now.</p>
        </Card>
      )}

      {seesAll && <StrategySignals />}
    </div>
  )
}

function FeaturedCard({ decision, dayScores }: { decision: BrainDecision; dayScores: (number | null)[] }) {
  const caps = useSymbolCaps()
  const candles = useQuery({
    queryKey: ['candles', decision.symbol, 30],
    queryFn: () => api.candles(decision.symbol, 30),
  })
  const points = (candles.data ?? []).map((c) => ({ t: c.ts.slice(5, 10), v: c.close }))

  return (
    <Card glow title="Featured Idea" sub="The top TRADE idea, or the top WATCH idea when there is no TRADE">
      <div className="tm-flex" style={{ gap: '0.7rem', alignItems: 'center', marginBottom: '0.6rem' }}>
        <StockLogo symbol={decision.symbol} />
        <span className="tm-strong" style={{ fontSize: '0.95rem' }}>
          {decision.symbol}
          <CapFlag tier={caps.get(decision.symbol.toUpperCase())} gap />
        </span>
        <div style={{ flex: 1, minWidth: 120 }}>
          {candles.isLoading && <p className="tm-dim">Loading price…</p>}
          {candles.isError && <p className="tm-dim">Price history not available.</p>}
          {points.length > 0 && <GlowArea data={points} height={70} formatter={(v) => `₹${inr(v, 0)}`} />}
        </div>
      </div>
      <LiveIdeaCard decision={decision} dayScores={dayScores} />
      <Link className="tm-btn tm-feature-btn" style={{ marginTop: '0.6rem' }} to={`/trademind/stock/${encodeURIComponent(decision.symbol)}`}>
        View Details
      </Link>
    </Card>
  )
}
