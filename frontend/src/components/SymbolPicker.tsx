import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'

interface SymbolPickerProps {
  value: string[]
  onChange: (symbols: string[]) => void
  placeholder?: string
}

/** Type-to-search symbol picker backed by GET /instruments?search=.
 *
 * Falls back to accepting a raw typed symbol on Enter — the instrument
 * master has to be synced from Kite before it has anything to match, and a
 * blank dropdown shouldn't block entering a symbol you already know. */
export default function SymbolPicker({ value, onChange, placeholder }: SymbolPickerProps) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 250)
    return () => clearTimeout(timer)
  }, [query])

  const search = useQuery({
    queryKey: ['instrumentSearch', debounced],
    queryFn: () => api.instruments(debounced, 8),
    enabled: debounced.length >= 1,
    staleTime: 60_000,
  })

  const suggestions = (search.data ?? []).filter((i) => !value.includes(i.tradingsymbol))

  const add = (symbol: string) => {
    const clean = symbol.trim().toUpperCase()
    if (clean && !value.includes(clean)) onChange([...value, clean])
    setQuery('')
    setOpen(false)
  }

  const remove = (symbol: string) => onChange(value.filter((s) => s !== symbol))

  return (
    <div className="symbol-picker">
      <div className="symbol-picker-chips">
        {value.map((s) => (
          <span className="chip" key={s}>
            {s}
            <button type="button" onClick={() => remove(s)} aria-label={`Remove ${s}`}>
              ×
            </button>
          </span>
        ))}
        <input
          value={query}
          placeholder={value.length ? '' : (placeholder ?? 'Type to search…')}
          onChange={(event) => {
            setQuery(event.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ',') {
              event.preventDefault()
              if (query.trim()) add(query)
            } else if (event.key === 'Backspace' && !query && value.length) {
              remove(value[value.length - 1])
            } else if (event.key === 'Escape') {
              setOpen(false)
            }
          }}
        />
      </div>

      {open && debounced.length >= 1 && (
        <div className="symbol-picker-dropdown">
          {suggestions.length ? (
            suggestions.map((instrument) => (
              <button
                type="button"
                key={instrument.id}
                className="symbol-picker-option"
                // mousedown fires before the input's blur, so the click still
                // registers instead of the dropdown closing first
                onMouseDown={(event) => {
                  event.preventDefault()
                  add(instrument.tradingsymbol)
                }}
              >
                <strong>{instrument.tradingsymbol}</strong>
                <span className="muted">{instrument.name}</span>
              </button>
            ))
          ) : (
            <div className="symbol-picker-empty">
              {search.isFetching
                ? 'Searching…'
                : `No match — press Enter to add "${query.trim().toUpperCase()}" anyway`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
