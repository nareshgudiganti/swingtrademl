// The new look's Discover: every stock the brain checked on its latest run, best first, with tonight's word, its
// place in the ranking, one short reason and where the brain stopped it. Display only — it reads the brain's latest
// run (and the sector map when this account may read it) and changes nothing. The classic card list, with its paper
// test-buy button and the version 1 strategy signals, stays one tap away (?view=cards).

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'

import { api } from '../../api/client'
import { formatDateTime } from '../../lib/format'
import { useSymbolCaps } from '../cap'
import {
  DISCOVER_FILTERS,
  DISCOVER_FOOT,
  discoverCounts,
  filterIdeas,
  sectorsIn,
  type DiscoverFilter,
} from '../discoverRules'
import { noTradeReason } from '../emptyReasons'
import { ideasFrom, useLatestRun } from '../live'
import { scoreRank } from '../scoreText'
import { IdeasTable, useIdeaSort } from '../IdeasTable'
import { BrainGate, Icon } from '../ui'
import '../newlook-w2.css'
import Opportunities from './Opportunities'

const FILTER_LABEL: Record<DiscoverFilter, string> = { ALL: 'All', TRADE: 'BUY', WATCH: 'WATCH', WAIT: 'WAIT', AVOID: 'AVOID' }


export default function DiscoverNew() {
  const [params] = useSearchParams()
  // The classic card list (paper test buys, strategy signals) keeps working in the new look.
  if (params.get('view') === 'cards') {
    return (
      <div className="tmn-w2-classic">
        <Link to="/trademind/opportunities" className="tmn-small tm-link tmn-w2-back">
          ← Back to the Discover table
        </Link>
        <Opportunities />
      </div>
    )
  }
  return (
    <BrainGate>
      <DiscoverBody />
    </BrainGate>
  )
}

function DiscoverBody() {
  const run = useLatestRun().data!
  const ideas = ideasFrom(run)
  const caps = useSymbolCaps()
  const [filter, setFilter] = useState<DiscoverFilter>('ALL')
  const [sector, setSector] = useState<string>('')
  const [query, setQuery] = useState('')

  // The sector map (ml/sector_map.py). Not every account may read it; without it the sector filter is hidden.
  const symbols = useMemo(() => ideas.map((d) => d.symbol.toUpperCase()).sort(), [ideas])
  const sectors = useQuery({
    queryKey: ['sectors', symbols.join(',')],
    queryFn: () => api.sectors(symbols),
    enabled: symbols.length > 0,
    retry: false,
    staleTime: 60 * 60_000,
  })
  const sectorOf = sectors.data
  const sectorList = sectorsIn(ideas, sectorOf)

  const counts = discoverCounts(ideas)
  const filtered = filterIdeas(ideas, { filter, sector: sector || null, query, sectorOf })
  const { sorted: rows, sorter } = useIdeaSort(filtered)
  const dayScores = ideas.map((d) => d.confidence)
  const noTrade = noTradeReason(run.banner, ideas.length, counts.TRADE)

  return (
    <div className="tm-page tmn-w2" data-page="discover-new">
      <div className="tmn-w2-head">
        <div>
          <h2 className="tmn-w2-h1">Discover</h2>
          <p className="tm-dim tmn-w2-intro">
            Every stock the brain checked on its last run, best first — and where each one stopped.
          </p>
        </div>
        <span className="tm-dim tmn-small">Brain’s run on {formatDateTime(run.started_at)}</span>
      </div>

      <div className="tmn-w2-toolbar">
        <div className="tmn-w2-pills" role="group" aria-label="Filter by decision" data-testid="discover-filters">
          {DISCOVER_FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              className={`tmn-w2-pill ${filter === f ? 'on' : ''}`}
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
            >
              {FILTER_LABEL[f]} <span className="tmn-w2-count">{counts[f]}</span>
            </button>
          ))}
        </div>
        <span className="tmn-grow" />
        {sectorList.length > 0 && (
          <label className="tmn-w2-select tm-dim tmn-small">
            Sector
            <select value={sector} onChange={(e) => setSector(e.target.value)} data-testid="sector-filter">
              <option value="">All sectors</option>
              {sectorList.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="tmn-w2-search">
          <Icon.Search size={13} />
          <input
            type="search"
            placeholder="Find a stock"
            aria-label="Find a stock in this list"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>

      {noTrade && ideas.length > 0 && (
        <p className="tmn-w2-note" data-testid="no-trade-reason">
          {noTrade}
        </p>
      )}

      <section className="tmn-card tmn-w2-tablecard" aria-label="Stocks the brain checked">
        {rows.length === 0 ? (
          <p className="tm-dim tmn-w2-empty" data-state="empty">
            {ideas.length === 0 ? (noTrade ?? 'The brain checked no stocks on its last run.') : 'No stocks match these filters.'}
          </p>
        ) : (
          <IdeasTable
            rows={rows}
            sorter={sorter}
            rankOf={(d) => scoreRank(d.confidence, dayScores)?.rank ?? null}
            tierOf={(d) => caps.get(d.symbol.toUpperCase())}
            sectorOf={sectorOf}
          />
        )}
      </section>

      <p className="tm-dim tmn-small tmn-w2-foot" data-testid="discover-foot">
        {DISCOVER_FOOT}
      </p>
      <p className="tmn-small">
        <Link className="tm-link" to="/trademind/opportunities?view=cards">
          Open the card view (paper test buys and strategy signals) →
        </Link>
      </p>
    </div>
  )
}
