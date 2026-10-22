// Stock search box (bx7). Not mounted yet. StockSearchView is pure (text, results, callbacks);
// StockSearch is the thin wrapper that debounces, queries the existing /instruments?search= and navigates.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../../api/client'

export type SearchHit = { tradingsymbol: string; name: string | null }

export function stockUrl(symbol: string): string {
  return `/trademind/stock/${encodeURIComponent(symbol)}`
}

/** Which result Enter picks: the highlighted one, else the first; -1 when the list is empty. */
export function pickIndex(count: number, highlighted: number): number {
  if (count <= 0) return -1
  return highlighted >= 0 && highlighted < count ? highlighted : 0
}

type ViewProps = {
  query: string
  results: SearchHit[]
  loading?: boolean
  onQuery: (q: string) => void
  onPick: (symbol: string) => void
}

export function StockSearchView({ query, results, loading, onQuery, onPick }: ViewProps) {
  const [active, setActive] = useState(0)
  const trimmed = query.trim()
  const open = trimmed.length >= 2
  return (
    <div className="bx-search">
      <input
        type="search"
        className="bx-search-input"
        placeholder="Search a stock…"
        aria-label="Search a stock"
        value={query}
        onChange={(e) => {
          setActive(0)
          onQuery(e.target.value)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && results.length) {
            e.preventDefault()
            setActive((a) => Math.min(a + 1, results.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setActive((a) => Math.max(a - 1, 0))
          } else if (e.key === 'Enter') {
            const i = pickIndex(results.length, active)
            if (i >= 0) onPick(results[i]!.tradingsymbol)
          }
        }}
      />
      {open && results.length > 0 && (
        <ul className="bx-search-list" role="listbox">
          {results.map((r, i) => (
            <li key={r.tradingsymbol} role="option" aria-selected={i === active}>
              <button type="button" className={i === active ? 'bx-search-hit bx-active' : 'bx-search-hit'} onClick={() => onPick(r.tradingsymbol)}>
                <strong>{r.tradingsymbol}</strong> {r.name && <span className="bx-small">{r.name}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && !loading && results.length === 0 && <p className="bx-small">No stock found</p>}
    </div>
  )
}

export default function StockSearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250)
    return () => clearTimeout(t)
  }, [query])
  const enabled = debounced.length >= 2
  const q = useQuery({
    queryKey: ['bx-stock-search', debounced],
    queryFn: () => api.instruments(debounced),
    enabled,
  })
  return (
    <StockSearchView
      query={query}
      results={enabled ? (q.data ?? []) : []}
      loading={enabled && q.isFetching}
      onQuery={setQuery}
      onPick={(s) => {
        setQuery('')
        navigate(stockUrl(s))
      }}
    />
  )
}
