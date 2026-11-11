// Groww Tracker (new look): stocks the person bought in Groww after the app's advice, each followed like an open
// position: how far it is from the stop and the target, how many days are done, and whether the model still likes
// it. Data: GET /me/watchlist/tracker. The status of each stock is the server's; nothing is recomputed here.
// Display and bookkeeping only: nothing on this page places an order.

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { SoldRecord, TrackerState, WatchTracker, WatchTrackerItem } from '../../api/types'
import { useLatestRun } from '../live'
import { QueryNotice } from '../PageState'
import { useSort, type Sorter } from '../sort'
import {
  ACT_CARDS,
  BAR_HI,
  BAR_LO,
  FILTERS,
  HALF_PCT,
  STATE_LABEL,
  STOP_PCT,
  TARGET_PCT,
  barPosition,
  dayNumber,
  deltaView,
  entryNote,
  filterItems,
  fmtBoughtOn,
  fmtPct,
  fmtPrice,
  buildPatch,
  fmtMoney,
  fmtRupees,
  formFromItem,
  needsActionCount,
  pips,
  portfolioSummary,
  scoreText,
  signClass,
  soldSummary,
  sortItems,
  stopTarget,
  symbolsIn,
  todayIst,
  whatToDo,
  type EditForm,
  type TrackerFilter,
} from '../trackerRules'
import { useTrackerTab } from '../trackerTab'
import { AddStock } from './WatchlistNew'
import '../newlook-w2.css'
import '../newlook-tracker.css'

export const TRACKER_KEY = ['myWatchlistTracker']
export const SOLD_KEY = ['myWatchlistSold']

type TrackerSortKey = 'symbol' | 'day' | 'bought' | 'paid' | 'shares' | 'since' | 'today' | 'score' | 'range' | 'trend' | 'status'

// Status sorts by urgency (stop first), the same ranking the page starts with.
const STATUS_RANK: Record<TrackerState, number> = { stop: 0, target: 1, time: 2, weak: 3, ok: 4 }

const TRACKER_SORT: Record<TrackerSortKey, (k: WatchTrackerItem) => number | string | null> = {
  symbol: (k) => k.symbol,
  day: (k) => dayNumber(k),
  bought: (k) => k.bought_on,
  paid: (k) => k.buy_price ?? k.entry_price,
  shares: (k) => k.quantity,
  since: (k) => k.return_pct,
  today: (k) => k.today_pct,
  score: (k) => k.score_today,
  range: (k) => k.return_pct, // where the stock sits between the stop and the target is its return
  trend: (k) => k.score_delta,
  status: (k) => STATUS_RANK[k.state],
}
// First click: A-Z for the stock name and most urgent first for status; every number sorts biggest first.
const TRACKER_FIRST_DIR: Partial<Record<TrackerSortKey, 'asc' | 'desc'>> = { symbol: 'asc', status: 'asc' }

function HeadSort<K extends string>({ sorter, k, children }: { sorter: Sorter<K>; k: K; children: string }) {
  const active = sorter.key === k
  return (
    <div role="columnheader" aria-sort={active ? (sorter.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="tm-sort" onClick={() => sorter.toggle(k)}>
        {children}
        <span className="tm-sort-arrow" aria-hidden>
          {active ? (sorter.dir === 'asc' ? '▲' : '▼') : '↕'}
        </span>
      </button>
    </div>
  )
}

export default function GrowwTracker() {
  const client = useQueryClient()
  const q = useQuery({ queryKey: TRACKER_KEY, queryFn: api.myWatchlistTracker, retry: false, staleTime: 30_000 })
  const latest = useLatestRun()
  const [tabOn, setTabOn] = useTrackerTab()
  const [filter, setFilter] = useState<TrackerFilter>('all')
  const [picked, setPicked] = useState<string | null>(null)
  // 'sold' shows the Sold records instead of the stocks being followed.
  const [view, setView] = useState<'following' | 'sold'>('following')
  const soldQ = useQuery({ queryKey: SOLD_KEY, queryFn: api.myWatchlistSoldList, retry: false, staleTime: 30_000 })
  // The stock whose Edit form is open (one at a time). Opening it also picks the stock.
  const [editSym, setEditSym] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    void client.invalidateQueries({ queryKey: TRACKER_KEY })
    void client.invalidateQueries({ queryKey: SOLD_KEY })
    void client.invalidateQueries({ queryKey: ['myWatchlist'] })
  }
  const add = useMutation({
    mutationFn: (symbol: string) => api.myWatchlistAdd(symbol),
    onSuccess: () => {
      setError(null)
      refresh()
    },
    onError: (e) => setError((e as Error).message),
  })

  const data: WatchTracker | undefined = q.data
  const horizon = data?.horizon_days && data.horizon_days > 0 ? data.horizon_days : 15
  const base = useMemo(() => (data ? sortItems(data.items) : []), [data])
  // Click a column heading to sort by it; click again to reverse. Until then: the urgent-first order above.
  const { sorted: all, sorter } = useSort<WatchTrackerItem, TrackerSortKey>(base, TRACKER_SORT, { key: null }, TRACKER_FIRST_DIR)
  const shown = filterItems(all, filter)
  const summary = useMemo(() => portfolioSummary(all), [all])
  const soldView = view === 'sold'
  const soldItems = soldQ.data?.items ?? []
  const selected = all.find((i) => i.symbol === picked) ?? shown[0] ?? all[0] ?? null

  return (
    <div className="tm-page gt" data-page="groww-tracker">
      <div className="gt-head">
        <div>
          <h2 className="gt-h1">Groww Tracker</h2>
          <p className="tm-dim gt-lead">
            Stocks you bought in Groww after the app’s advice. Each one is followed like an open position: how far it is
            from the stop and the target, how many days are done, and whether the model still likes it.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={tabOn}
          className="gt-switch"
          onClick={() => setTabOn(!tabOn)}
          data-testid="tracker-tab-switch"
        >
          Show this tab in the menu <span className="gt-tog" aria-hidden="true" />
        </button>
      </div>

      {!tabOn && (
        <div className="gt-off" data-testid="tracker-tab-off">
          <span>This tab is hidden from your menu. This page still opens from its link.</span>
          <button type="button" className="gt-ghost" onClick={() => setTabOn(true)}>
            Show it in the menu again
          </button>
        </div>
      )}

      <p className="tm-dim tmn-small">Paper trading only. Nothing here places an order.</p>

      {data === undefined ? (
        <QueryNotice q={q} what="your Groww tracker" />
      ) : (
        <>
          <QueryNotice q={q} what="your Groww tracker" />
          {!soldView && summary && (
            <section className="gt-sum" aria-label="Your Groww stocks in total" data-testid="tracker-summary">
              <div>
                <div className="gt-sum-l">Invested value</div>
                <div className="gt-sum-v num">{fmtRupees(summary.invested)}</div>
              </div>
              <div>
                <div className="gt-sum-l">1D returns</div>
                <div className={`gt-sum-v num ${signClass(summary.dayReturn)}`}>
                  {fmtMoney(summary.dayReturn)} <small>({fmtPct(summary.dayReturnPct, 2)})</small>
                </div>
              </div>
              <div>
                <div className="gt-sum-l">Total returns</div>
                <div className={`gt-sum-v num ${signClass(summary.totalReturn)}`}>
                  {fmtMoney(summary.totalReturn)} <small>({fmtPct(summary.totalReturnPct, 2)})</small>
                </div>
              </div>
              {summary.counted < all.length && (
                <p className="tm-dim tmn-small gt-sum-note">
                  Counts {summary.counted} of {all.length} stocks. Add shares and the price paid to the others to include them.
                </p>
              )}
            </section>
          )}
          {!soldView && (
          <section className="gt-act" aria-label="Act today" data-testid="act-strip">
            {ACT_CARDS.map((c) => {
              const syms = symbolsIn(all, c.state)
              return (
                <div key={c.state} className={`gt-card k-${c.state}`}>
                  <h3>{c.title}</h3>
                  <div className="gt-big num">{syms.length}</div>
                  <div className="gt-who">{syms.length ? syms.join(', ') : 'None'}</div>
                </div>
              )
            })}
          </section>
          )}

          <div className="gt-bar" role="group" aria-label="Filter">
            {FILTERS.map((f) => (
              <button key={f.id} type="button" className="gt-chip" aria-pressed={!soldView && filter === f.id} onClick={() => {
                setView('following')
                setFilter(f.id)
              }}>
                {f.id === 'all' ? `All (${all.length})` : f.label}
              </button>
            ))}
            <button type="button" className="gt-chip" aria-pressed={soldView} onClick={() => setView('sold')} data-testid="sold-chip">
              Sold records ({soldItems.length})
            </button>
            <button type="button" className="tmn-w2-primary gt-add" onClick={() => setAdding((a) => !a)} aria-expanded={adding} data-testid="add-bought">
              {adding ? 'Close' : '+ Add stock I bought'}
            </button>
          </div>

          {soldView ? (
            <SoldRecords q={soldQ} items={soldItems} />
          ) : (
            <>
          {adding && <AddStock run={latest.data} onAdd={(s) => add.mutateAsync(s)} busy={add.isPending} />}
          {error && (
            <p className="tm-neg tmn-small" role="alert">
              {error}
            </p>
          )}

          {all.length === 0 ? (
            <section className="tmn-card gt-empty" data-state="empty">
              <p>
                <b>You are not following any stock yet.</b>
              </p>
              <p className="tm-dim">
                When you buy a stock in Groww after the app’s advice, tap “Add stock I bought”. It will then be followed
                here day by day, with a clear word on what to do.
              </p>
            </section>
          ) : (
            <div className="gt-split">
              <div className="gt-tbl" role="region" aria-label="Table, scroll sideways to see more" tabIndex={0} data-testid="tracker-table">
                <div className="gt-grid gt-headrow">
                  <HeadSort sorter={sorter} k="symbol">Stock</HeadSort>
                  <HeadSort sorter={sorter} k="day">Day</HeadSort>
                  <HeadSort sorter={sorter} k="bought">Bought on</HeadSort>
                  <HeadSort sorter={sorter} k="paid">Price paid</HeadSort>
                  <HeadSort sorter={sorter} k="shares">Shares</HeadSort>
                  <HeadSort sorter={sorter} k="since">Since added</HeadSort>
                  <HeadSort sorter={sorter} k="today">Today</HeadSort>
                  <HeadSort sorter={sorter} k="score">Score today</HeadSort>
                  <HeadSort sorter={sorter} k="range">Stop ← → Target</HeadSort>
                  <HeadSort sorter={sorter} k="trend">Score, last days</HeadSort>
                  <HeadSort sorter={sorter} k="status">Status</HeadSort>
                  <div>Edit</div>
                </div>
                {shown.length === 0 ? (
                  <div className="gt-grid dim">No stock matches this filter.</div>
                ) : (
                  shown.map((k) =>
                    editSym === k.symbol ? (
                      <EditableRow
                        key={`${k.symbol}-${k.bought_on}-${k.buy_price}-${k.quantity}-${k.note}`}
                        k={k}
                        horizon={horizon}
                        onSaved={() => {
                          setEditSym(null)
                          refresh()
                        }}
                        onCancel={() => setEditSym(null)}
                      />
                    ) : (
                      <Row
                        key={k.symbol}
                        k={k}
                        horizon={horizon}
                        selected={selected?.symbol === k.symbol}
                        onPick={() => setPicked(k.symbol)}
                        onEdit={() => {
                          setPicked(k.symbol)
                          setEditSym(k.symbol)
                        }}
                      />
                    ),
                  )
                )}
              </div>
              {selected && (
                <aside className="gt-side">
                <Detail
                  key={selected.symbol}
                  k={selected}
                  horizon={horizon}
                  editing={editSym === selected.symbol}
                  onEditing={(open) => setEditSym(open ? selected.symbol : null)}
                  onRemoved={() => {
                    setPicked(null)
                    setEditSym(null)
                    refresh()
                  }}
                />
                </aside>
              )}
            </div>
          )}
            </>
          )}
          {!soldView && (
          <p className="tm-dim tmn-small">
            {needsActionCount(all)} of {all.length} need a look today. The plan for each stock: +8% target, −4% stop, sell
            half at +5%, and be out within {horizon} trading days.
          </p>
          )}
        </>
      )}
    </div>
  )
}

function StateChip({ state }: { state: TrackerState }) {
  return <span className={`gt-state s-${state}`}>{STATE_LABEL[state]}</span>
}

function Pips({ days, horizon }: { days: number; horizon: number }) {
  return (
    <span className="gt-pips" aria-hidden="true">
      {pips(days, horizon).map((p, i) => (
        <i key={i} className={`gt-pip${p.filled ? ' f' : ''}${p.late ? ' late' : ''}`} />
      ))}
    </span>
  )
}

function Bar({ ret }: { ret: number | null }) {
  const x = barPosition(ret)
  const mark = (v: number) => ((v - BAR_LO) / (BAR_HI - BAR_LO)) * 100
  return (
    <>
      <div className="gt-prog" role="img" aria-label={ret == null ? 'No price yet' : `Return ${fmtPct(ret)} between the stop and the target`}>
        <b style={{ left: `${mark(0)}%` }} />
        {x != null && <i style={{ left: `${x}%` }} />}
      </div>
      <div className="gt-pl num">
        <span>−{Math.abs(STOP_PCT)}%</span>
        <span>0</span>
        <span>+{HALF_PCT}%</span>
        <span>+{TARGET_PCT}%</span>
      </div>
    </>
  )
}

function Spark({ scores }: { scores: { score: number }[] }) {
  const sc = scores.map((s) => s.score).filter((v) => Number.isFinite(v))
  if (sc.length < 2) return <span className="dim">—</span>
  const w = 120
  const h = 26
  const lo = 40
  const hi = 100
  const pts = sc.map((v, i) => [(i * (w - 6)) / (sc.length - 1) + 3, h - 3 - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (h - 6)] as const)
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ')
  const up = sc[sc.length - 1]! >= sc[0]!
  const col = up ? 'var(--tm-green-2)' : 'var(--tm-red)'
  const e = pts[pts.length - 1]!
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label="Score trend">
      <path d={d} fill="none" stroke={col} strokeWidth="1.6" />
      <circle cx={e[0]} cy={e[1]} r="2.6" fill={col} />
    </svg>
  )
}

function DayCell({ k, horizon }: { k: WatchTrackerItem; horizon: number }) {
  return (
    <div>
      <b className="num">{dayNumber(k)}</b>
      <span className="dim"> of {horizon}</span>
      <br />
      <Pips days={dayNumber(k)} horizon={horizon} />
    </div>
  )
}

/** The columns from "Since added" to "Status": numbers the server works out, never editable. */
function MarketCells({ k }: { k: WatchTrackerItem }) {
  const dv = deltaView(k.score_delta)
  return (
    <>
      <div className={`num ${signClass(k.return_pct)}`}>
        <b>{fmtPct(k.return_pct)}</b>
        <div className="gt-sub">
          {fmtPrice(k.entry_price)} → {fmtPrice(k.last_price)}
        </div>
      </div>
      <div className={`num ${signClass(k.today_pct)}`}>{fmtPct(k.today_pct, 2)}</div>
      <div className="gt-score">
        <b className="num">{scoreText(k.score_today)}</b>
        <span className={`num ${dv.tone}`}>
          {dv.arrow} {dv.text}
        </span>
      </div>
      <div>
        <Bar ret={k.return_pct} />
      </div>
      <div>
        <Spark scores={k.scores} />
      </div>
      <div>
        <StateChip state={k.state} />
      </div>
    </>
  )
}

// A div, not a button, so the Edit button inside it is valid HTML; Enter and Space still pick the row.
function Row({ k, horizon, selected, onPick, onEdit }: { k: WatchTrackerItem; horizon: number; selected: boolean; onPick: () => void; onEdit: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      className={`gt-grid gt-row${selected ? ' sel' : ''}`}
      onClick={onPick}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onPick()
        }
      }}
      aria-pressed={selected}
      data-symbol={k.symbol}
    >
      <div>
        <div className="gt-sym">{k.symbol}</div>
        <div className="gt-sub">{k.name ?? ''}</div>
        {k.note && <div className="gt-sub gt-notetext">{k.note}</div>}
      </div>
      <DayCell k={k} horizon={horizon} />
      <div className="num" data-testid={`bought-${k.symbol}`}>
        {fmtBoughtOn(k.bought_on)}
      </div>
      <div className="num" title={k.buy_price == null ? 'No Groww price saved. The close on the buy date is the start.' : undefined}>
        {fmtPrice(k.buy_price)}
      </div>
      <div className="num">{k.quantity != null ? k.quantity.toLocaleString('en-IN') : '—'}</div>
      <MarketCells k={k} />
      <div>
        <button
          type="button"
          className="gt-ghost gt-edit-btn"
          data-testid={`edit-${k.symbol}`}
          aria-label={`Edit ${k.symbol}`}
          onClick={(e) => {
            e.stopPropagation()
            onEdit()
          }}
        >
          Edit
        </button>
      </div>
    </div>
  )
}

/**
 * The same row with its entry values turned into boxes: buy date, price paid, shares and a note. Enter saves,
 * Escape cancels. Only changed fields are sent. Exported for tests.
 */
export function EditableRow({
  k,
  horizon,
  onSaved,
  onCancel,
  initial,
}: {
  k: WatchTrackerItem
  horizon: number
  onSaved: () => void
  onCancel: () => void
  /** Tests only: start with these values typed in and the errors already showing. */
  initial?: Partial<EditForm>
}) {
  const [form, setForm] = useState<EditForm>(() => ({ ...formFromItem(k), ...initial }))
  const [serverError, setServerError] = useState<string | null>(null)
  const [tried, setTried] = useState(initial !== undefined)
  const today = todayIst()
  const { patch, errors, changed } = buildPatch(k, form, today)
  const update = useMutation({
    mutationFn: () => api.myWatchlistUpdate(k.symbol, patch),
    onSuccess: () => {
      setServerError(null)
      onSaved()
    },
    onError: (e) => setServerError((e as Error).message),
  })
  const set = (field: keyof EditForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [field]: e.target.value }))
  const messages = tried ? Object.values(errors) : []
  const bad = Object.keys(errors).length > 0
  return (
    <>
      <form
        className="gt-grid gt-row gt-editing"
        data-testid="edit-row"
        data-symbol={k.symbol}
        aria-label={`Edit ${k.symbol}`}
        onSubmit={(e) => {
          e.preventDefault()
          setTried(true)
          if (bad) return
          if (!changed) return onCancel()
          update.mutate()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.preventDefault()
            onCancel()
          }
        }}
      >
        <div>
          <div className="gt-sym">{k.symbol}</div>
          <div className="gt-sub">{k.name ?? ''}</div>
          <input
            type="text"
            className="gt-cell gt-cell-note"
            value={form.note}
            onChange={set('note')}
            placeholder="Note for yourself"
            aria-label={`Note for ${k.symbol}`}
            maxLength={200}
          />
        </div>
        <DayCell k={k} horizon={horizon} />
        <div>
          <input type="date" className="gt-cell" value={form.boughtOn} max={today} onChange={set('boughtOn')} aria-label={`Bought on for ${k.symbol}`} />
        </div>
        <div>
          <input
            type="text"
            inputMode="decimal"
            className="gt-cell"
            value={form.price}
            onChange={set('price')}
            placeholder="₹ paid"
            aria-label={`Price you paid in Groww for ${k.symbol}`}
          />
        </div>
        <div>
          <input
            type="text"
            inputMode="decimal"
            className="gt-cell"
            value={form.quantity}
            onChange={set('quantity')}
            placeholder="shares"
            aria-label={`Shares of ${k.symbol}`}
          />
        </div>
        <MarketCells k={k} />
        <div className="gt-editbtns">
          <button type="submit" className="tmn-w2-primary" disabled={update.isPending}>
            {update.isPending ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="gt-ghost" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
      {(messages.length > 0 || serverError) && (
        <div className="gt-rowerr tm-neg tmn-small" role="alert" data-testid="edit-row-error">
          {messages.map((m) => (
            <div key={m}>{m}</div>
          ))}
          {serverError && <div>{serverError}</div>}
        </div>
      )}
    </>
  )
}

// ------------------------------------------------------------------ charts --

const dayLabels = (n: number, x: (i: number) => number, H: number) =>
  Array.from({ length: n }, (_, i) =>
    i === 0 || i === n - 1 || i % 3 === 0 ? (
      <text key={i} x={x(i)} y={H - 6} textAnchor="middle">
        D{i}
      </text>
    ) : null,
  )

function ScoreChart({ scores }: { scores: { score: number }[] }) {
  const sc = scores.map((s) => s.score).filter((v) => Number.isFinite(v))
  const n = sc.length
  if (n === 0) return <p className="dim tmn-small">No score yet. The model scores your stocks after the market closes (about 16:30 IST); the first point appears then.</p>
  const W = 420
  const H = 170
  const L = 30
  const R = 10
  const T = 10
  const B = 24
  const lo = 40
  const hi = 100
  const x = (i: number) => L + (n > 1 ? (i * (W - L - R)) / (n - 1) : (W - L - R) / 2)
  const y = (v: number) => T + ((hi - Math.max(lo, Math.min(hi, v))) / (hi - lo)) * (H - T - B)
  const d = sc.map((v, i) => `${i ? 'L' : 'M'}${x(i)} ${y(v)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Model score each day since added">
      {[40, 60, 80, 100].map((v) => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--tm-line)" />
          <text x={L - 5} y={y(v) + 3} textAnchor="end">
            {v}
          </text>
        </g>
      ))}
      <rect x={L} y={y(100)} width={W - L - R} height={y(80) - y(100)} fill="var(--tm-green)" opacity=".07" />
      <rect x={L} y={y(60)} width={W - L - R} height={y(40) - y(60)} fill="var(--tm-red)" opacity=".07" />
      <path d={d} fill="none" stroke="var(--tm-blue)" strokeWidth="2" />
      {sc.map((v, i) => (
        <circle key={i} cx={x(i)} cy={y(v)} r={i === n - 1 ? 4 : 2.4} fill="var(--tm-blue)" />
      ))}
      {dayLabels(n, x, H)}
      <text x={x(n - 1)} y={y(sc[n - 1]!) - 9} textAnchor="end" style={{ fill: 'var(--tm-text)', fontWeight: 600 }}>
        {Math.round(sc[n - 1]!)}
      </text>
    </svg>
  )
}

function ReturnChart({ closes, entry }: { closes: { close: number }[]; entry: number | null }) {
  const c = closes.map((p) => p.close).filter((v) => Number.isFinite(v) && v > 0)
  const n = c.length
  if (entry == null || entry <= 0) return <p className="dim tmn-small">Add your Groww buy price to see the return chart.</p>
  if (n < 2) return <p className="dim tmn-small">Not enough days yet. The chart appears after the first close.</p>
  const W = 420
  const H = 170
  const L = 34
  const R = 10
  const T = 14
  const B = 24
  const lo = BAR_LO
  const hi = BAR_HI
  const clamp = (v: number) => Math.max(lo, Math.min(hi, v))
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B)
  const bw = Math.max(4, Math.min(18, (W - L - R) / n - 6))
  const x = (i: number) => L + ((i + 0.5) * (W - L - R)) / n
  const cum = c.map((v) => (v / entry - 1) * 100)
  const moves = c.map((v, i) => (i ? (v / c[i - 1]! - 1) * 100 : 0))
  const line = cum.map((v, i) => `${i ? 'L' : 'M'}${x(i)} ${y(clamp(v))}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Return since added and each day's move">
      {[STOP_PCT, 0, HALF_PCT, TARGET_PCT].map((v) => (
        <g key={v}>
          <line
            x1={L}
            x2={W - R}
            y1={y(v)}
            y2={y(v)}
            stroke={v === 0 ? 'var(--tm-dim)' : v === STOP_PCT ? 'var(--tm-red)' : v === TARGET_PCT ? 'var(--tm-green)' : 'var(--tm-line)'}
            strokeDasharray={v === 0 ? undefined : '4 3'}
          />
          <text x={L - 5} y={y(v) + 3} textAnchor="end">
            {v > 0 ? '+' : v < 0 ? '−' : ''}
            {Math.abs(v)}%
          </text>
        </g>
      ))}
      {moves.map((v, i) =>
        i === 0 ? null : (
          <rect
            key={i}
            x={x(i) - bw / 2}
            y={y(clamp(Math.max(v, 0)))}
            width={bw}
            height={Math.max(1.5, Math.abs(y(clamp(v)) - y(0)))}
            fill={v >= 0 ? 'var(--tm-green)' : 'var(--tm-red)'}
            opacity=".55"
          />
        ),
      )}
      <path d={line} fill="none" stroke="var(--tm-text)" strokeWidth="2" />
      <circle cx={x(n - 1)} cy={y(clamp(cum[n - 1]!))} r="4" fill="var(--tm-text)" />
      {dayLabels(n, x, H)}
    </svg>
  )
}

// ------------------------------------------------------------------ detail --

function Detail({
  k,
  horizon,
  editing,
  onEditing,
  onRemoved,
}: {
  k: WatchTrackerItem
  horizon: number
  editing: boolean
  onEditing: (open: boolean) => void
  onRemoved: () => void
}) {
  const [mode, setMode] = useState<'none' | 'sold'>('none')
  const [error, setError] = useState<string | null>(null)

  const remove = useMutation({
    mutationFn: () => api.myWatchlistRemove(k.symbol),
    onSuccess: onRemoved,
    onError: (e) => setError((e as Error).message),
  })
  // The price starts at today's price as a suggestion; the person should type what Groww really paid out.
  const [sellPrice, setSellPrice] = useState(k.last_price != null ? String(k.last_price) : '')
  const [soldOn, setSoldOn] = useState(todayIst())
  const sell = useMutation({
    mutationFn: () => api.myWatchlistSold(k.symbol, { sell_price: Number(sellPrice), sold_on: soldOn }),
    onSuccess: onRemoved,
    onError: (e) => setError((e as Error).message),
  })
  const priceOk = Number.isFinite(Number(sellPrice)) && Number(sellPrice) > 0

  const dv = deltaView(k.score_delta)
  const st = stopTarget(k.entry_price)

  return (
    <section className="gt-detail" aria-live="polite" data-testid="tracker-detail" data-symbol={k.symbol}>
      <div className="gt-dh">
        <h2>{k.symbol}</h2>
        {k.name && <span className="dim">{k.name}</span>}
        <StateChip state={k.state} />
        {k.note && <span className="dim">{k.note}</span>}
      </div>
      <div className="gt-facts">
        <div className="gt-fact">
          <span>Day</span>
          <b className="num">
            {dayNumber(k)} of {horizon}
          </b>
        </div>
        <div className="gt-fact">
          <span>Return since added</span>
          <b className={`num ${signClass(k.return_pct)}`}>{fmtPct(k.return_pct)}</b>
        </div>
        <div className="gt-fact">
          <span>Today</span>
          <b className={`num ${signClass(k.today_pct)}`}>{fmtPct(k.today_pct, 2)}</b>
        </div>
        <div className="gt-fact">
          <span>Score today</span>
          <b className="num">
            {scoreText(k.score_today)} <small className={dv.tone}>{dv.arrow === '–' ? '' : `${dv.arrow}${dv.text}`}</small>
          </b>
        </div>
        <div className="gt-fact" title={entryNote(k)}>
          <span>{k.entry_source === 'added_close' ? 'Price when added' : 'Your Groww price'}</span>
          <b className="num">{fmtPrice(k.entry_price)}</b>
        </div>
        <div className="gt-fact">
          <span>Stop / Target</span>
          <b className="num">
            {st ? `${fmtPrice(st.stop)} (${fmtPct(STOP_PCT, 0)}) / ${fmtPrice(st.target)} (${fmtPct(TARGET_PCT, 0)})` : '—'}
          </b>
          {st && k.last_price != null && k.last_price > 0 && (
            <small className="dim">
              From today’s price: stop {fmtPct((st.stop / k.last_price - 1) * 100)}, target {fmtPct((st.target / k.last_price - 1) * 100)}
            </small>
          )}
        </div>
        <div className="gt-fact" data-testid="fact-bought-on">
          <span>Bought on</span>
          <b className="num">{fmtBoughtOn(k.bought_on)}</b>
        </div>
        <div className="gt-fact">
          <span>Shares</span>
          <b className="num">{k.quantity != null ? k.quantity.toLocaleString('en-IN') : '—'}</b>
        </div>
        <div className="gt-fact">
          <span>Invested</span>
          <b className="num">{fmtRupees(k.invested)}</b>
        </div>
        <div className="gt-fact">
          <span>Profit / loss</span>
          <b className={`num ${signClass(k.profit_amount)}`}>{fmtMoney(k.profit_amount)}</b>
        </div>
      </div>
      {(k.entry_source === 'added_close' || k.quantity == null) && (
        <p className="dim tmn-small">
          {k.entry_source === 'added_close' ? 'No Groww price saved, so the close on the buy date is used as the start. ' : ''}
          {k.quantity == null ? 'Add your shares to see profit and loss in rupees. ' : ''}
          Tap Edit to change the date, price or shares in the row above.
        </p>
      )}

      <div className="gt-charts">
        <div className="gt-chart">
          <h4>Model score, day by day</h4>
          <ScoreChart scores={k.scores} />
          <div className="gt-legend">
            <span style={{ ['--c' as string]: 'var(--tm-green)' }}>80+ strong</span>
            <span style={{ ['--c' as string]: 'var(--tm-red)' }}>under 60 weak</span>
          </div>
        </div>
        <div className="gt-chart">
          <h4>Return since added, and each day’s move</h4>
          <ReturnChart closes={k.closes} entry={k.entry_price} />
          <div className="gt-legend">
            <span style={{ ['--c' as string]: 'var(--tm-text)' }}>Total return</span>
            <span style={{ ['--c' as string]: 'var(--tm-green)' }}>Up day</span>
            <span style={{ ['--c' as string]: 'var(--tm-red)' }}>Down day</span>
          </div>
        </div>
      </div>

      <p className="gt-why" data-testid="what-to-do">
        <b>What to do:</b> {whatToDo(k, horizon)}
      </p>

      {mode === 'sold' && (
        <div className="gt-edit gt-sellform" role="group" aria-label={`Record the sale of ${k.symbol}`}>
          <span>
            Sold <b>{k.symbol}</b> in Groww? Enter the price you got. It moves to <b>Sold records</b> with its profit or loss.
            Nothing is sold by this app.
          </span>
          <label>
            Sold at (₹ per share)
            <input
              className="gt-cell"
              inputMode="decimal"
              value={sellPrice}
              onChange={(e) => setSellPrice(e.target.value)}
              aria-label={`Sell price for ${k.symbol}`}
            />
          </label>
          <label>
            Sold on
            <input
              type="date"
              className="gt-cell"
              value={soldOn}
              max={todayIst()}
              onChange={(e) => setSoldOn(e.target.value)}
              aria-label={`Sell date for ${k.symbol}`}
            />
          </label>
          <button type="button" className="gt-ghost sold-yes" disabled={!priceOk || sell.isPending} onClick={() => sell.mutate()}>
            Save sale
          </button>
          <button type="button" className="gt-ghost" onClick={() => setMode('none')}>
            Keep it
          </button>
          <button
            type="button"
            className="gt-ghost"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
            title="For a stock you never bought: it is removed and no result is kept"
          >
            Just remove it, no result
          </button>
        </div>
      )}
      {error && (
        <p className="tm-neg tmn-small" role="alert">
          {error}
        </p>
      )}

      <div className="gt-actions">
        <button type="button" className="gt-ghost" aria-expanded={editing} onClick={() => onEditing(!editing)} data-testid="detail-edit">
          {editing ? 'Close edit' : 'Edit in the row'}
        </button>
        <button type="button" className="gt-ghost sold" onClick={() => setMode('sold')}>
          I sold it in Groww
        </button>
      </div>
    </section>
  )
}


type SoldSortKey = 'symbol' | 'bought' | 'sold' | 'days' | 'paid' | 'sellp' | 'shares' | 'ret' | 'profit'

const SOLD_SORT: Record<SoldSortKey, (r: SoldRecord) => number | string | null> = {
  symbol: (r) => r.symbol,
  bought: (r) => r.bought_on,
  sold: (r) => r.sold_on,
  days: (r) => r.days_held,
  paid: (r) => r.entry_price,
  sellp: (r) => r.sell_price,
  shares: (r) => r.quantity,
  ret: (r) => r.return_pct,
  profit: (r) => r.profit_amount,
}

// Newest sale first until a heading is clicked (the server sends them that way).
function SoldRecords({ q, items }: { q: Parameters<typeof QueryNotice>[0]['q']; items: SoldRecord[] }) {
  const { sorted, sorter } = useSort<SoldRecord, SoldSortKey>(items, SOLD_SORT, { key: null }, { symbol: 'asc' })
  const sum = useMemo(() => soldSummary(items), [items])
  if (items.length === 0) {
    return (
      <section className="tmn-card gt-empty" data-state="no-sold" data-testid="sold-empty">
        <QueryNotice q={q} what="your sold records" />
        <p>
          <b>No sold stocks yet.</b>
        </p>
        <p className="tm-dim">
          When you sell a stock in Groww, open it here and tap “I sold it in Groww”. Its profit or loss is then kept in this list.
        </p>
      </section>
    )
  }
  return (
    <>
      <section className="gt-sum" aria-label="Your sold stocks in total" data-testid="sold-summary">
        <div>
          <div className="gt-sum-l">Invested in sold stocks</div>
          <div className="gt-sum-v num">{fmtRupees(sum.invested)}</div>
        </div>
        <div>
          <div className="gt-sum-l">Made or lost on sales</div>
          <div className={`gt-sum-v num ${signClass(sum.profit)}`}>
            {fmtMoney(sum.profit)} <small>({fmtPct(sum.profitPct, 2)})</small>
          </div>
        </div>
        <div>
          <div className="gt-sum-l">Sales that made money</div>
          <div className="gt-sum-v num">
            {sum.wins} of {sum.decided}
          </div>
        </div>
        {sum.withoutShares > 0 && (
          <p className="tm-dim tmn-small gt-sum-note">
            {sum.withoutShares} sale{sum.withoutShares === 1 ? '' : 's'} had no shares entered, so only the % is shown for
            them and they are left out of the rupee totals.
          </p>
        )}
      </section>
      <div className="gt-tbl" role="region" aria-label="Sold records, scroll sideways to see more" tabIndex={0} data-testid="sold-table">
        <div className="gt-grid gt-sold-grid gt-headrow">
          <HeadSort sorter={sorter} k="symbol">Stock</HeadSort>
          <HeadSort sorter={sorter} k="bought">Bought on</HeadSort>
          <HeadSort sorter={sorter} k="sold">Sold on</HeadSort>
          <HeadSort sorter={sorter} k="days">Days held</HeadSort>
          <HeadSort sorter={sorter} k="paid">Price paid</HeadSort>
          <HeadSort sorter={sorter} k="sellp">Sold at</HeadSort>
          <HeadSort sorter={sorter} k="shares">Shares</HeadSort>
          <HeadSort sorter={sorter} k="ret">Return</HeadSort>
          <HeadSort sorter={sorter} k="profit">Profit / loss</HeadSort>
        </div>
        {sorted.map((r, i) => (
          <div key={`${r.symbol}-${r.sold_on}-${i}`} className="gt-grid gt-sold-grid gt-row" data-testid={`sold-${r.symbol}`}>
            <div>
              <div className="gt-sym">{r.symbol}</div>
              <div className="gt-sub">{r.name ?? ''}</div>
            </div>
            <div className="num">{fmtBoughtOn(r.bought_on)}</div>
            <div className="num">{fmtBoughtOn(r.sold_on)}</div>
            <div className="num">{r.days_held}</div>
            <div className="num">{fmtPrice(r.entry_price)}</div>
            <div className="num">{fmtPrice(r.sell_price)}</div>
            <div className="num">{r.quantity ?? '—'}</div>
            <div className={`num ${signClass(r.return_pct)}`}>
              <b>{fmtPct(r.return_pct, 2)}</b>
            </div>
            <div className={`num ${signClass(r.profit_amount)}`}>
              <b>{fmtMoney(r.profit_amount)}</b>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
