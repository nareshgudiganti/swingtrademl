// Groww Tracker (new look): stocks the person bought in Groww after the app's advice, each followed like an open
// position: how far it is from the stop and the target, how many days are done, and whether the model still likes
// it. Data: GET /me/watchlist/tracker. The status of each stock is the server's; nothing is recomputed here.
// Display and bookkeeping only: nothing on this page places an order.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { TrackerState, WatchTracker, WatchTrackerItem } from '../../api/types'
import { useLatestRun } from '../live'
import { QueryNotice } from '../PageState'
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
  deltaView,
  entryNote,
  filterItems,
  fmtPct,
  fmtPrice,
  needsActionCount,
  parseBuyPrice,
  pips,
  scoreText,
  signClass,
  sortItems,
  stopTarget,
  symbolsIn,
  whatToDo,
  type TrackerFilter,
} from '../trackerRules'
import { useTrackerTab } from '../trackerTab'
import { AddStock } from './WatchlistNew'
import '../newlook-w2.css'
import '../newlook-tracker.css'

export const TRACKER_KEY = ['myWatchlistTracker']

export default function GrowwTracker() {
  const client = useQueryClient()
  const q = useQuery({ queryKey: TRACKER_KEY, queryFn: api.myWatchlistTracker, retry: false, staleTime: 30_000 })
  const latest = useLatestRun()
  const [tabOn, setTabOn] = useTrackerTab()
  const [filter, setFilter] = useState<TrackerFilter>('all')
  const [picked, setPicked] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    void client.invalidateQueries({ queryKey: TRACKER_KEY })
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
  const all = data ? sortItems(data.items) : []
  const shown = filterItems(all, filter)
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

          <div className="gt-bar" role="group" aria-label="Filter">
            {FILTERS.map((f) => (
              <button key={f.id} type="button" className="gt-chip" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                {f.id === 'all' ? `All (${all.length})` : f.label}
              </button>
            ))}
            <button type="button" className="tmn-w2-primary gt-add" onClick={() => setAdding((a) => !a)} aria-expanded={adding} data-testid="add-bought">
              {adding ? 'Close' : '+ Add stock I bought'}
            </button>
          </div>

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
            <>
              <div className="gt-tbl" role="region" aria-label="Table, scroll sideways to see more" tabIndex={0} data-testid="tracker-table">
                <div className="gt-grid gt-headrow">
                  <div>Stock</div>
                  <div>Day</div>
                  <div>Since added</div>
                  <div>Today</div>
                  <div>Score today</div>
                  <div>Stop ← → Target</div>
                  <div>Score, last days</div>
                  <div>Status</div>
                </div>
                {shown.length === 0 ? (
                  <div className="gt-grid dim">No stock matches this filter.</div>
                ) : (
                  shown.map((k) => <Row key={k.symbol} k={k} horizon={horizon} selected={selected?.symbol === k.symbol} onPick={() => setPicked(k.symbol)} />)
                )}
              </div>
              {selected && (
                <Detail
                  key={selected.symbol}
                  k={selected}
                  horizon={horizon}
                  onChanged={refresh}
                  onRemoved={() => {
                    setPicked(null)
                    refresh()
                  }}
                />
              )}
            </>
          )}
          <p className="tm-dim tmn-small">
            {needsActionCount(all)} of {all.length} need a look today. The plan for each stock: +8% target, −4% stop, sell
            half at +5%, and be out within {horizon} trading days.
          </p>
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

function Row({ k, horizon, selected, onPick }: { k: WatchTrackerItem; horizon: number; selected: boolean; onPick: () => void }) {
  const dv = deltaView(k.score_delta)
  return (
    <button type="button" className={`gt-grid gt-row${selected ? ' sel' : ''}`} onClick={onPick} aria-pressed={selected} data-symbol={k.symbol}>
      <div>
        <div className="gt-sym">{k.symbol}</div>
        <div className="gt-sub">{k.name ?? ''}</div>
      </div>
      <div>
        <b className="num">{k.days_done}</b>
        <span className="dim"> of {horizon}</span>
        <br />
        <Pips days={k.days_done} horizon={horizon} />
      </div>
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
    </button>
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
  if (n === 0) return <p className="dim tmn-small">No score yet for this stock.</p>
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

function Detail({ k, horizon, onChanged, onRemoved }: { k: WatchTrackerItem; horizon: number; onChanged: () => void; onRemoved: () => void }) {
  const [mode, setMode] = useState<'none' | 'price' | 'note' | 'sold'>('none')
  const [price, setPrice] = useState(k.buy_price != null ? String(k.buy_price) : '')
  const [note, setNote] = useState(k.note ?? '')
  const [error, setError] = useState<string | null>(null)

  const update = useMutation({
    mutationFn: (body: { buy_price?: number | null; note?: string | null }) => api.myWatchlistUpdate(k.symbol, body),
    onSuccess: () => {
      setError(null)
      setMode('none')
      onChanged()
    },
    onError: (e) => setError((e as Error).message),
  })
  const remove = useMutation({
    mutationFn: () => api.myWatchlistRemove(k.symbol),
    onSuccess: onRemoved,
    onError: (e) => setError((e as Error).message),
  })

  const dv = deltaView(k.score_delta)
  const st = stopTarget(k.entry_price)
  const parsed = parseBuyPrice(price)

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
            {k.days_done} of {horizon}
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
          <b className="num">{st ? `${fmtPrice(st.stop)} / ${fmtPrice(st.target)}` : '—'}</b>
        </div>
      </div>
      {k.entry_source === 'added_close' && (
        <p className="dim tmn-small">
          No Groww price saved, so the day you added it is used as the start. Tap “Edit my Groww buy price” to use what you paid.
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

      {mode === 'price' && (
        <form
          className="gt-edit"
          onSubmit={(e) => {
            e.preventDefault()
            if (parsed !== undefined) update.mutate({ buy_price: parsed })
          }}
        >
          <label>
            <span className="tm-dim tmn-small">Price you paid in Groww (₹), empty to clear </span>
            <input type="text" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} aria-label="Your Groww buy price" autoFocus />
          </label>
          <button type="submit" className="tmn-w2-primary" disabled={update.isPending || parsed === undefined}>
            Save price
          </button>
          <button type="button" className="gt-ghost" onClick={() => setMode('none')}>
            Cancel
          </button>
          {parsed === undefined && <span className="tm-neg tmn-small">Type a number above 0, like 4210 or 182.4.</span>}
        </form>
      )}
      {mode === 'note' && (
        <form
          className="gt-edit"
          onSubmit={(e) => {
            e.preventDefault()
            update.mutate({ note: note.trim() === '' ? null : note.trim() })
          }}
        >
          <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="A short note for yourself" aria-label="Note" autoFocus maxLength={200} />
          <button type="submit" className="tmn-w2-primary" disabled={update.isPending}>
            Save note
          </button>
          <button type="button" className="gt-ghost" onClick={() => setMode('none')}>
            Cancel
          </button>
        </form>
      )}
      {mode === 'sold' && (
        <div className="gt-edit" role="alertdialog" aria-label={`Remove ${k.symbol}`}>
          <span>
            Remove <b>{k.symbol}</b> from the tracker? Do this once you have sold it in Groww. Nothing is sold by this app.
          </span>
          <button type="button" className="gt-ghost sold-yes" disabled={remove.isPending} onClick={() => remove.mutate()}>
            Yes, remove it
          </button>
          <button type="button" className="gt-ghost" onClick={() => setMode('none')}>
            Keep it
          </button>
        </div>
      )}
      {error && (
        <p className="tm-neg tmn-small" role="alert">
          {error}
        </p>
      )}

      <div className="gt-actions">
        <button type="button" className="gt-ghost" onClick={() => setMode(mode === 'price' ? 'none' : 'price')}>
          Edit my Groww buy price
        </button>
        <button type="button" className="gt-ghost" onClick={() => setMode(mode === 'note' ? 'none' : 'note')}>
          Add a note
        </button>
        <button type="button" className="gt-ghost sold" onClick={() => setMode('sold')}>
          I sold it in Groww, remove
        </button>
      </div>
    </section>
  )
}
