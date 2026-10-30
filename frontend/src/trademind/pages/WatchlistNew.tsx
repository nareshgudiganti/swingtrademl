// My Watchlist (new look): each signed-in person's own list of stocks, with the brain's read on each from its last
// run. The list lives on the server (GET/POST/DELETE /me/watchlist) and belongs to this person only; it never
// changes which stocks the bot trades (that is the owner's global watchlist, a different list). Removing a stock is
// not destructive: it moves to "Removed", where one tap adds it back.

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainRun } from '../../api/types'
import { CapFlag, useSymbolCaps } from '../cap'
import { useLatestRun } from '../live'
import { QueryNotice } from '../PageState'
import { rankText, SCORE_HINT, scorePoints } from '../scoreText'
import { WordTag } from '../term'
import { SortTh, useSort } from '../sort'
import { Icon, StockLogo } from '../ui'
import { addedDate, rowsFor, tabCounts, watchRows, type WatchRow, type WatchTab } from '../watchlistRules'
import '../newlook-w2.css'

const TABS: { id: WatchTab; label: string; hint?: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'watching', label: 'Watching' },
  {
    id: 'close',
    label: 'Close to a BUY',
    hint: 'A TRADE on the brain’s last run, or stopped only by the account’s safety limits after passing every other check.',
  },
  { id: 'removed', label: 'Removed' },
]

const KEY = ['myWatchlist']

export default function WatchlistNew() {
  const client = useQueryClient()
  const list = useQuery({ queryKey: KEY, queryFn: api.myWatchlist })
  const latest = useLatestRun()
  const run = latest.data
  const [tab, setTab] = useState<WatchTab>('all')
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const changed = () => client.invalidateQueries({ queryKey: KEY })
  const remove = useMutation({
    mutationFn: (symbol: string) => api.myWatchlistRemove(symbol),
    onSuccess: changed,
    onError: (e) => setError((e as Error).message),
  })
  const add = useMutation({
    mutationFn: (symbol: string) => api.myWatchlistAdd(symbol),
    onSuccess: () => {
      setError(null)
      return changed()
    },
    onError: (e) => setError((e as Error).message),
  })

  const rows = list.data ? watchRows(list.data.items, run) : []
  const counts = tabCounts(rows)
  const { sorted: shown, sorter } = useSort(rowsFor(rows, tab), {
    stock: (r: WatchRow) => r.item.symbol,
    tonight: (r: WatchRow) => r.word ?? null,
    score: (r: WatchRow) => (r.decision ? r.decision.confidence : null),
    added: (r: WatchRow) => r.item.removed_at ?? r.item.added_at,
  }, { key: null }, { stock: 'asc', tonight: 'asc' })
  const limit = list.data?.limit ?? null

  return (
    <div className="tm-page tmn-w2" data-page="watchlist-new">
      <div className="tmn-w2-head">
        <div>
          <h2 className="tmn-w2-h1">My Watchlist</h2>
          <p className="tm-dim tmn-w2-intro">
            Your own list of stocks{list.data ? ` (${counts.all}${limit ? ` of ${limit}` : ''})` : ''}. The brain reads
            each one every evening and shows its word here.
          </p>
        </div>
        <button type="button" className="tmn-w2-primary" onClick={() => setAdding((a) => !a)} aria-expanded={adding} data-testid="add-stock">
          {adding ? 'Close' : '+ Add a stock'}
        </button>
      </div>

      {adding && <AddStock run={run} onAdd={(s) => add.mutateAsync(s)} busy={add.isPending} />}
      {error && (
        <p className="tm-neg tmn-small" role="alert">
          {error}
        </p>
      )}

      <div className="tmn-w2-pills" role="group" aria-label="Show" data-testid="watch-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tmn-w2-pill ${tab === t.id ? 'on' : ''}`}
            aria-pressed={tab === t.id}
            title={t.hint}
            onClick={() => setTab(t.id)}
          >
            {t.label} <span className="tmn-w2-count">{counts[t.id]}</span>
          </button>
        ))}
      </div>

      <section className="tmn-card tmn-w2-tablecard" aria-label="My watchlist">
        {list.data === undefined ? (
          <div className="tmn-w2-pad">
            <QueryNotice q={list} what="your watchlist" />
          </div>
        ) : shown.length === 0 ? (
          <p className="tm-dim tmn-w2-empty" data-state="empty">
            {emptyText(tab, counts.all)}
          </p>
        ) : (
          <div className="tmn-w2-tablebox" role="region" aria-label="Table, scroll sideways to see more" tabIndex={0}>
            <table className="tmn-w2-table" data-testid="watch-table">
              <thead>
                <tr>
                  <SortTh sorter={sorter} k="stock">Stock</SortTh>
                  <SortTh sorter={sorter} k="tonight">Tonight</SortTh>
                  <SortTh sorter={sorter} k="score" title={SCORE_HINT}>Score</SortTh>
                  <th>What it is waiting for</th>
                  <SortTh sorter={sorter} k="added">{tab === 'removed' ? 'Removed' : 'Added'}</SortTh>
                  <th>
                    <span className="tmn-w2-sr">{tab === 'removed' ? 'Add back' : 'Remove'}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <Row
                    key={r.item.symbol}
                    r={r}
                    busy={remove.isPending || add.isPending}
                    onRemove={() => {
                      setError(null)
                      remove.mutate(r.item.symbol)
                    }}
                    onAddBack={() => add.mutate(r.item.symbol)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {!run && latest.isError && (
        <p className="tm-dim tmn-small">The brain’s last run could not be loaded, so tonight’s words are not shown.</p>
      )}
      <p className="tm-dim tmn-small tmn-w2-foot">
        This list is yours only. It does not change which stocks the bot trades. The score ranks the brain’s ideas
        against each other on the same night; it is not a chance of profit.
      </p>
    </div>
  )
}

function emptyText(tab: WatchTab, onList: number): string {
  if (tab === 'removed') return 'Nothing removed.'
  if (onList === 0) return 'Your list is empty. Tap “Add a stock” to start.'
  if (tab === 'close') return 'None of your stocks is close to a BUY on the brain’s last run.'
  return 'Nothing here.'
}

function Row({ r, busy, onRemove, onAddBack }: { r: WatchRow; busy: boolean; onRemove: () => void; onAddBack: () => void }) {
  const caps = useSymbolCaps()
  const to = `/trademind/stock/${encodeURIComponent(r.item.symbol)}`
  const pts = r.decision ? scorePoints(r.decision.confidence) : null
  return (
    <tr>
      <td>
        <Link to={to} className="tmn-w2-stock">
          <StockLogo symbol={r.item.symbol} />
          <span>
            <b>{r.item.symbol}</b> <CapFlag tier={caps.get(r.item.symbol.toUpperCase())} />
            {r.item.name && <span className="tm-dim tmn-small tmn-w2-sub">{r.item.name}</span>}
          </span>
        </Link>
      </td>
      <td>{r.word ? <WordTag word={r.word} /> : <span className="tm-dim tmn-small">Not checked</span>}</td>
      <td title={r.rank ? `${rankText(r.rank)}. ${SCORE_HINT}` : SCORE_HINT}>
        <b>{pts ?? '—'}</b>
        {r.rank && <span className="tm-dim tmn-small tmn-w2-sub">#{r.rank.rank} of {r.rank.of}</span>}
      </td>
      <td className="tmn-w2-why">
        {r.close && !r.removed ? <span className="tmn-w2-close">{r.waitingFor}</span> : r.waitingFor}
      </td>
      <td className="tm-dim">{addedDate(r.item.removed_at ?? r.item.added_at)}</td>
      <td>
        {r.removed ? (
          <button type="button" className="tmn-w2-ghost" disabled={busy} onClick={onAddBack} aria-label={`Add ${r.item.symbol} back`}>
            Add back
          </button>
        ) : (
          <button type="button" className="tmn-w2-x" disabled={busy} onClick={onRemove} aria-label={`Remove ${r.item.symbol}`} title="Remove from my list">
            ×
          </button>
        )}
      </td>
    </tr>
  )
}

/** Search the NSE list by symbol or company name, then add. Says whether the brain checked the stock on its last run. */
function AddStock({ run, onAdd, busy }: { run: BrainRun | undefined; onAdd: (symbol: string) => Promise<unknown>; busy: boolean }) {
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250)
    return () => clearTimeout(t)
  }, [text])
  const hits = useQuery({ queryKey: ['myWatchlistSearch', q], queryFn: () => api.myWatchlistSearch(q), enabled: q.length > 0, retry: false })
  const checked = new Set((run?.decisions ?? []).map((d) => d.symbol.toUpperCase()))

  return (
    <section className="tmn-card tmn-w2-add" aria-label="Add a stock">
      <label className="tmn-w2-search tmn-w2-search-wide">
        <Icon.Search size={13} />
        <input
          type="search"
          autoFocus
          placeholder="Type a stock name or symbol, e.g. RELIANCE"
          aria-label="Search for a stock to add"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      {q && hits.isError && <p className="tm-neg tmn-small">{(hits.error as Error).message}</p>}
      {q && hits.data?.length === 0 && <p className="tm-dim tmn-small">No stock on the NSE matches “{q}”.</p>}
      {hits.data && hits.data.length > 0 && (
        <ul className="tmn-w2-hits" data-testid="search-hits">
          {hits.data.map((h) => (
            <li key={h.symbol}>
              <span className="tmn-grow">
                <b>{h.symbol}</b> <span className="tm-dim tmn-small">{h.name ?? ''}</span>
                <span className="tm-dim tmn-small tmn-w2-sub">
                  {checked.has(h.symbol.toUpperCase()) ? 'The brain checked it on its last run.' : 'Not in the brain’s last run: it may show as “Not checked”.'}
                </span>
              </span>
              <button
                type="button"
                className="tmn-w2-ghost"
                disabled={busy}
                onClick={() => {
                  void onAdd(h.symbol).then(() => setText('')).catch(() => {})
                }}
              >
                Add
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
