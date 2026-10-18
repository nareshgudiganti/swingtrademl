// Click-to-sort table headers. Click once: sort by that column (biggest / latest
// first, or the column's own natural order); click again: reverse it.

import { useMemo, useState, type ReactNode } from 'react'

export type SortValue = number | string | null | undefined
export type SortDir = 'asc' | 'desc'

export interface Sorter<K extends string> {
  key: K | null
  dir: SortDir
  toggle: (key: K) => void
}

/**
 * `getters` maps each sortable column to the value it sorts by. `firstDir`
 * says which way a column sorts on its first click (default: biggest first);
 * a ranking such as "Sell before Hold" uses 'asc'. Empty values always go last.
 */
export function useSort<T, K extends string>(
  rows: T[],
  getters: Record<K, (row: T) => SortValue>,
  initial: { key: K | null; dir?: SortDir } = { key: null },
  firstDir: Partial<Record<K, SortDir>> = {},
): { sorted: T[]; sorter: Sorter<K> } {
  const [key, setKey] = useState<K | null>(initial.key)
  const [dir, setDir] = useState<SortDir>(initial.dir ?? 'desc')

  const sorted = useMemo(() => {
    if (!key) return rows
    const get = getters[key]
    const sign = dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = get(a)
      const bv = get(b)
      const aEmpty = av == null || av === ''
      const bEmpty = bv == null || bv === ''
      if (aEmpty || bEmpty) return aEmpty === bEmpty ? 0 : aEmpty ? 1 : -1
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sign
      return String(av).localeCompare(String(bv)) * sign
    })
    // getters is a fresh object each render; the rows/key/dir drive the sort.
  }, [rows, key, dir])

  const toggle = (next: K) => {
    if (next === key) {
      setDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setKey(next)
      setDir(firstDir[next] ?? 'desc')
    }
  }

  return { sorted, sorter: { key, dir, toggle } }
}

export function SortTh<K extends string>({
  sorter,
  k,
  children,
  right = false,
  title,
}: {
  sorter: Sorter<K>
  k: K
  children: ReactNode
  right?: boolean
  title?: string
}) {
  const active = sorter.key === k
  return (
    <th
      className={right ? 'tm-right' : undefined}
      aria-sort={active ? (sorter.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      title={title}
    >
      <button type="button" className="tm-sort" onClick={() => sorter.toggle(k)}>
        {children}
        <span className="tm-sort-arrow" aria-hidden>
          {active ? (sorter.dir === 'asc' ? '▲' : '▼') : '↕'}
        </span>
      </button>
    </th>
  )
}
