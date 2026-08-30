import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { LatestSignal } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDateTime, formatPercent } from '../lib/format'

type SortKey = 'generated_at' | 'symbol' | 'signal' | 'price' | 'quantity' | 'confidence' | 'stop_loss' | 'take_profit'
type SortDir = 'asc' | 'desc'

const COLUMNS: { key: SortKey; label: string; num?: boolean; defaultDir: SortDir }[] = [
  { key: 'generated_at', label: 'Time', defaultDir: 'desc' },
  { key: 'symbol', label: 'Symbol', defaultDir: 'asc' },
  { key: 'signal', label: 'Signal', defaultDir: 'asc' },
  { key: 'price', label: 'Price', num: true, defaultDir: 'desc' },
  { key: 'quantity', label: 'Qty', num: true, defaultDir: 'desc' },
  { key: 'confidence', label: 'Confidence', num: true, defaultDir: 'desc' },
  { key: 'stop_loss', label: 'Stop', num: true, defaultDir: 'desc' },
  { key: 'take_profit', label: 'Target', num: true, defaultDir: 'desc' },
]

// nulls always sort last, regardless of direction — a missing stop/target/qty
// isn't "low", it's not comparable, and burying it at the bottom either way
// keeps the click behavior predictable.
function compare(a: LatestSignal, b: LatestSignal, key: SortKey): number {
  const av = a[key]
  const bv = b[key]
  if (av == null && bv == null) return 0
  if (av == null) return 1
  if (bv == null) return -1
  if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv)
  if (typeof av === 'number' && typeof bv === 'number') return av - bv
  return 0
}

export default function Signals() {
  // `search` is the raw typed text (drives the suggestions dropdown);
  // `selectedSymbol` is only set once an exact instrument is picked — the
  // signal-history lookup is an exact match server-side, so typing "HDFC"
  // alone must never be sent as the query, only "HDFCBANK" etc. once chosen.
  const [search, setSearch] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selectedSymbol, setSelectedSymbol] = useState('')
  const [dropdownOpen, setDropdownOpen] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(search.trim()), 250)
    return () => clearTimeout(timer)
  }, [search])

  const suggestions = useQuery({
    queryKey: ['instrumentSearch', debouncedQuery],
    queryFn: () => api.instruments(debouncedQuery, 8),
    enabled: debouncedQuery.length >= 1 && !selectedSymbol,
    staleTime: 60_000,
  })

  const signals = useQuery({
    queryKey: selectedSymbol ? ['signalHistory', selectedSymbol] : ['signals', 100],
    queryFn: () => (selectedSymbol ? api.signalHistory(selectedSymbol) : api.latestSignals(100)),
    // Keeps the previous result on screen while a new search resolves,
    // instead of swapping to a loading state on every keystroke — that
    // swap is also what was unmounting the input and losing focus/cursor
    // position on each character typed.
    placeholderData: keepPreviousData,
  })
  const [sortKey, setSortKey] = useState<SortKey>('generated_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  function selectSymbol(symbol: string) {
    setSelectedSymbol(symbol)
    setSearch(symbol)
    setDropdownOpen(false)
  }

  function clearSearch() {
    setSelectedSymbol('')
    setSearch('')
    setDebouncedQuery('')
  }

  const rows = useMemo(() => {
    const data = [...(signals.data ?? [])]
    data.sort((a, b) => compare(a, b, sortKey) * (sortDir === 'asc' ? 1 : -1))
    return data
  }, [signals.data, sortKey, sortDir])

  function toggleSort(col: (typeof COLUMNS)[number]) {
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(col.key)
      setSortDir(col.defaultDir)
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Signals</h1>
        <span className="row" style={{ gap: '0.5rem' }}>
          <span style={{ position: 'relative', display: 'inline-block', minWidth: '240px' }}>
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setSelectedSymbol('')
                setDropdownOpen(true)
              }}
              onFocus={() => setDropdownOpen(true)}
              // mousedown on an option fires before this blur, so the click
              // still registers instead of the dropdown closing first
              onBlur={() => setTimeout(() => setDropdownOpen(false), 150)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  const first = suggestions.data?.[0]
                  selectSymbol(first ? first.tradingsymbol : search.trim().toUpperCase())
                } else if (e.key === 'Escape') {
                  setDropdownOpen(false)
                }
              }}
              placeholder="Search a symbol or company name…"
              style={{ width: '100%' }}
            />
            {dropdownOpen && debouncedQuery.length >= 1 && !selectedSymbol && (
              <div className="symbol-picker-dropdown">
                {(suggestions.data ?? []).length ? (
                  suggestions.data!.map((inst) => (
                    <button
                      type="button"
                      key={inst.id}
                      className="symbol-picker-option"
                      onMouseDown={(e) => {
                        e.preventDefault()
                        selectSymbol(inst.tradingsymbol)
                      }}
                    >
                      <strong>{inst.tradingsymbol}</strong>
                      <span className="muted">{inst.name}</span>
                    </button>
                  ))
                ) : (
                  <div className="symbol-picker-empty">
                    {suggestions.isFetching ? 'Searching…' : `No match for "${debouncedQuery}"`}
                  </div>
                )}
              </div>
            )}
          </span>
          {signals.isFetching && <span className="muted">loading…</span>}
        </span>
      </div>

      {selectedSymbol ? (
        <div className="banner banner-info">
          Showing every score for <strong>{selectedSymbol}</strong> — newest first, click a
          column to sort. Includes HOLD days, not just BUY/EXIT, so you can see how confidence
          has moved over time.{' '}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault()
              clearSearch()
            }}
            style={{ color: 'inherit', textDecoration: 'underline' }}
          >
            Clear search
          </a>
        </div>
      ) : (
        <div className="banner banner-info">
          {rows.length} most recent actionable signals across all strategies. Rejected signals are
          shown too — a signal the risk engine blocked is as much a part of the record as one it
          took, the rejection reason explains why.
        </div>
      )}

      <div className="table-wrap">
        {signals.isLoading ? (
          <Loading />
        ) : signals.error ? (
          <ErrorBox error={signals.error} />
        ) : !rows.length ? (
          <Empty
            label={
              selectedSymbol
                ? `No signals found for ${selectedSymbol} — it may not be part of an active strategy's universe.`
                : 'No signals yet. Activate a strategy, then run a scan.'
            }
          />
        ) : (
          <table>
            <thead>
              <tr>
                {COLUMNS.map((col, i) => (
                  <th
                    key={col.key}
                    className={`sortable${col.num ? ' num' : ''}${i === 0 ? ' sticky-col' : ''}`}
                    onClick={() => toggleSort(col)}
                    aria-sort={sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  >
                    {col.label}
                    <span className="sort-arrow">
                      {sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </span>
                  </th>
                ))}
                <th>Status</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td className="muted sticky-col">{formatDateTime(s.generated_at)}</td>
                  <td>
                    <strong>{s.symbol}</strong>
                  </td>
                  <td>
                    <span className={`badge badge-${s.signal.toLowerCase()}`}>{s.signal}</span>
                  </td>
                  <td className="num">{formatCurrency(s.price)}</td>
                  <td className="num">{s.quantity ?? '—'}</td>
                  <td className="num">
                    {s.confidence !== null ? formatPercent(s.confidence, 1) : '—'}
                  </td>
                  <td className="num muted">{s.stop_loss ? formatCurrency(s.stop_loss) : '—'}</td>
                  <td className="num muted">
                    {s.take_profit ? formatCurrency(s.take_profit) : '—'}
                  </td>
                  <td>
                    {s.executed ? (
                      <span className="badge badge-on">executed</span>
                    ) : s.advisory_only ? (
                      <span className="badge badge-recommend" title="Recommended — not auto-executed. Record the fill via POST /portfolio/positions/manual once taken.">
                        recommended
                      </span>
                    ) : (
                      <span className="badge badge-off">not taken</span>
                    )}
                  </td>
                  <td className="reason muted" title={s.rejection_reason ?? s.reason ?? ''}>
                    {s.rejection_reason ?? s.reason ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
