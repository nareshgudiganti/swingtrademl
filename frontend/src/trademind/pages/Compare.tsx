// Stock Compare: pick up to three stocks and see how far each one's price moved over the last week to five years.
// Display only: it reads stored daily closes and changes no pick, order, stop, size or limit. It says "Not enough
// history" instead of guessing, and the verdict on each stock stays on its own stock page (one tap away).

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'

import { api } from '../../api/client'
import type { CompareStock } from '../../api/types'
import { StockSearchView, stockUrl } from '../beginner/StockSearch'
import { MAX_COMPARE, fmtPct, leaderLine, noNumbersText, parseSelection, toneOf } from '../compareRules'
import '../stockpage.css'
import './compare.css'

function Picker({ onPick, disabled }: { onPick: (symbol: string) => void; disabled: boolean }) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250)
    return () => clearTimeout(t)
  }, [query])
  const enabled = !disabled && debounced.length >= 2
  const current = debounced === query.trim()
  const q = useQuery({ queryKey: ['bx-stock-search', debounced], queryFn: () => api.instruments(debounced), enabled })
  if (disabled) return <p className="sp-small">That is the most we can compare at once ({MAX_COMPARE}). Remove one to add another.</p>
  return (
    <StockSearchView
      query={query}
      results={enabled && current ? (q.data ?? []) : []}
      loading={!current || (enabled && q.isFetching)}
      failed={enabled && current && q.isError}
      onQuery={setQuery}
      onPick={(s) => {
        setQuery('')
        onPick(s)
      }}
    />
  )
}

function StockCard({ stock, periods, onRemove }: { stock: CompareStock; periods: string[]; onRemove: () => void }) {
  return (
    <section className="sp-card sp-stack cmp-card" data-testid={`compare-card-${stock.symbol}`} data-state={stock.state}>
      <header className="cmp-head">
        <div>
          <h3 className="sp-h3">{stock.symbol}</h3>
          {stock.name && <div className="sp-small">{stock.name}</div>}
        </div>
        <button type="button" className="cmp-remove" onClick={onRemove} aria-label={`Remove ${stock.symbol}`}>
          Remove
        </button>
      </header>
      {stock.state === 'ok' ? (
        <>
          <div className="cmp-tiles">
            {periods.map((p) => {
              const v = stock.returns[p] ?? null
              return (
                <div key={p} className="cmp-tile" data-tone={toneOf(v)} data-testid={`tile-${stock.symbol}-${p}`}>
                  <b>{v === null ? '–' : fmtPct(v)}</b>
                  <span>{p === '1W' ? '1 Week' : p.endsWith('M') ? `${p.slice(0, -1)} Month${p === '1M' ? '' : 's'}` : `${p.slice(0, -1)} Year${p === '1Y' ? '' : 's'}`}</span>
                </div>
              )
            })}
          </div>
          <p className="sp-small">
            Closing prices up to {stock.as_of}. A dash means we do not have that far back.
          </p>
        </>
      ) : (
        <p className="sp-bigtext" data-testid="compare-no-numbers">
          {noNumbersText(stock)}
        </p>
      )}
      {stock.state !== 'unknown' && (
        <Link className="sp-small" to={stockUrl(stock.symbol)}>
          Open {stock.symbol} for our view ›
        </Link>
      )}
    </section>
  )
}

export default function Compare() {
  const [params, setParams] = useSearchParams()
  const symbols = parseSelection(params.get('s'))
  const [period, setPeriod] = useState('3M')

  const set = (next: string[]) => setParams(next.length ? { s: next.join(',') } : {}, { replace: true })
  const q = useQuery({
    queryKey: ['compare', symbols.join(',')],
    queryFn: () => api.compare(symbols),
    enabled: symbols.length > 0,
    retry: false,
  })

  const stocks = q.data?.stocks ?? []
  const periods = q.data?.periods ?? []
  const line = leaderLine(stocks, period)

  return (
    <div className="tm-page sp" data-page="compare">
      <header>
        <h2 className="sp-h2" style={{ fontSize: 22 }}>
          Compare stocks
        </h2>
        <div className="sp-sub">Pick up to {MAX_COMPARE} stocks and see how far each price moved over time.</div>
      </header>

      <div className="sp-card sp-card-flat sp-stack">
        <Picker disabled={symbols.length >= MAX_COMPARE} onPick={(s) => set(parseSelection([...symbols, s].join(',')))} />
        <p className="sp-small">Price changes only. This is not advice to buy or sell.</p>
      </div>

      {symbols.length === 0 && (
        <p className="sp-bigtext" data-testid="compare-empty">
          Search for two or three stocks above to compare them.
        </p>
      )}
      {symbols.length > 0 && q.isLoading && <p className="sp-small">Loading…</p>}
      {symbols.length > 0 && q.isError && (
        <p className="sp-small" data-testid="compare-error">
          The comparison could not be loaded right now.
        </p>
      )}

      {stocks.length > 0 && (
        <>
          {periods.length > 0 && (
            <div className="sp-stack" style={{ gap: 8 }}>
              <div className="cmp-chips" role="group" aria-label="Period for the summary">
                {periods.map((p) => (
                  <button key={p} type="button" className="cmp-chip" aria-pressed={p === period} onClick={() => setPeriod(p)}>
                    {p}
                  </button>
                ))}
              </div>
              {line && (
                <p className="sp-bigtext" data-testid="compare-line">
                  {line}
                </p>
              )}
            </div>
          )}
          <div className="cmp-grid">
            {stocks.map((s) => (
              <StockCard key={s.symbol} stock={s} periods={periods} onRemove={() => set(symbols.filter((x) => x !== s.symbol))} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
