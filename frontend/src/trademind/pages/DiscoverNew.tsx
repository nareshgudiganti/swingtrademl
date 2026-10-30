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
import { ideasFrom, shownWord, useLatestRun } from '../live'
import { scoreRank } from '../scoreText'
import { StockRail, type RailCard } from '../StockRail'
import { BrainGate, Icon } from '../ui'
import { IdeasTable, useIdeaSort } from '../IdeasTable'
import { wordLabel } from '../vocab'
import '../newlook-w2.css'
import Opportunities from './Opportunities'

const FILTER_LABEL: Record<DiscoverFilter, string> = { ALL: 'All', TRADE: 'BUY', WATCH: 'WATCH', WAIT: 'WAIT', AVOID: 'AVOID' }

// The rows of the sliding view, best word first, and the tone each row's cards carry.
const RAILS = [
  { word: 'TRADE', title: 'BUY', sub: 'Passed every check', tone: 'up' },
  { word: 'WATCH', title: 'WATCH', sub: 'Good, but not a buy yet', tone: 'wait' },
  { word: 'WAIT', title: 'WAIT', sub: 'Nothing to do today', tone: 'wait' },
  { word: 'AVOID', title: 'AVOID', sub: 'Stay away for now', tone: 'down' },
] as const

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
  const [params] = useSearchParams()
  const run = useLatestRun().data!
  const ideas = ideasFrom(run)
  const caps = useSymbolCaps()
  const [filter, setFilter] = useState<DiscoverFilter>('ALL')
  const [sector, setSector] = useState<string>('')
  const [query, setQuery] = useState('')
  // The table is the default (owner, 2026-11-03); slides (swipe through rows of cards) stay one tap away.
  const [layout, setLayout] = useState<'slides' | 'table'>(params.get('layout') === 'slides' ? 'slides' : 'table')

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
        <div className="tmn-w2-sorttabs tmn-w2-layouttabs" role="group" aria-label="How to show the list">
          {(['slides', 'table'] as const).map((l) => (
            <button
              key={l}
              type="button"
              className="tmn-w2-sorttab"
              aria-pressed={layout === l}
              data-testid={`layout-${l}`}
              onClick={() => setLayout(l)}
            >
              {l === 'slides' ? 'Slides' : 'Table'}
            </button>
          ))}
        </div>
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

      {layout === 'slides' && rows.length > 0 && (
        <div className="tmn-w2-rails" data-testid="discover-slides">
          {RAILS.map((r) => {
            const cards: RailCard[] = rows
              .filter((d) => shownWord(d) === r.word)
              .map((d) => ({
                d,
                rank: scoreRank(d.confidence, dayScores)?.rank ?? null,
                tier: caps.get(d.symbol.toUpperCase()),
                sector: sectorOf?.[d.symbol.toUpperCase()] ?? null,
              }))
            if (cards.length === 0) return null
            return (
              <StockRail
                key={r.word}
                title={wordLabel(r.word)}
                sub={r.sub}
                tone={r.tone}
                cards={cards}
                onSeeAll={() => {
                  setFilter(r.word)
                  setLayout('table')
                }}
              />
            )
          })}
        </div>
      )}

      {(layout === 'table' || rows.length === 0) && (
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
      )}

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
