// Swing Picks dashboard: one place to see the brain's picks by time window.
// Read-only and frontend-only (plus one plain sector lookup): it reads the
// brain's latest run and the market data the other TradeMind screens read.
// It adds nothing to the brain.
//
// Only the 15-day window is real today (the brain plans +8% / -4% over up to
// 15 trading days, selling half at +5%). The other windows have no model and
// no track record, so their tabs say so instead of showing made-up picks.
// The score is a ranking between ideas, never shown as a chance of winning.

import { useMemo, useState } from 'react'
import { chancePercent, chanceText, chanceTitle } from '../honest'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainDecision, BrainRun, Candle } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import type { Action } from '../types'
import { finalWord, ideasFrom, stockSituations, useLatestRun } from '../live'
import { MARKET_LABEL, MARKET_PLAIN, MARKET_TONE, wordTone } from '../vocab'
import { ActionPill, BrainArt, BrainGate, Card, CheckItem, GlowArea, Meter, Ring, StockLogo, Tag, inr } from '../ui'

type Window = '5d' | '15d' | '30d' | '90d'

const WINDOWS: { id: Window; title: string; kind: string; span: string; live: boolean }[] = [
  { id: '5d', title: '5 Days', kind: 'Short swing', span: '3 - 7 trading days', live: false },
  { id: '15d', title: '15 Days', kind: 'Medium swing', span: 'up to 15 trading days', live: true },
  { id: '30d', title: '30 Days', kind: 'Positional swing', span: '3 - 6 weeks', live: false },
  { id: '90d', title: '3 Months', kind: 'Long swing', span: '6 - 12 weeks', live: false },
]

const RANGES = [
  { id: '1W', bars: 5 },
  { id: '1M', bars: 22 },
  { id: '3M', bars: 66 },
  { id: '6M', bars: 132 },
  { id: '1Y', bars: 252 },
] as const
type RangeId = (typeof RANGES)[number]['id']

const MIN_SCORES = [
  { id: 0, label: 'Any ranking' },
  { id: 60, label: 'Ranking 60+' },
  { id: 70, label: 'Ranking 70+' },
  { id: 80, label: 'Ranking 80+' },
]

const FIRST_TARGET = 0.05 // the rule: sell half at +5%

const money = (n: number | null | undefined) => (n == null ? '—' : `₹${inr(n)}`)
const score = (d: BrainDecision) => (d.confidence != null ? Math.round(d.confidence * 100) : null)

function entryMid(d: BrainDecision): number | null {
  if (d.entry_low != null && d.entry_high != null) return (d.entry_low + d.entry_high) / 2
  return d.entry_low ?? d.entry_high
}

function entryText(d: BrainDecision): string {
  if (d.entry_low != null && d.entry_high != null && d.entry_low !== d.entry_high) {
    return `₹${inr(d.entry_low)} – ₹${inr(d.entry_high)}`
  }
  return money(d.entry_low ?? d.entry_high)
}

function pct(from: number | null, to: number | null): string {
  if (from == null || to == null || from === 0) return ''
  const p = (to / from - 1) * 100
  return `${p >= 0 ? '+' : ''}${p.toFixed(1)}%`
}

/** What the daily candles say: last close, day change, 52-week range, volume. */
function quoteFrom(candles: Candle[] | undefined) {
  if (!candles || candles.length === 0) return null
  const last = candles[candles.length - 1]!
  const prev = candles.length > 1 ? candles[candles.length - 2]! : null
  const year = candles.slice(-252)
  return {
    price: last.close,
    change: prev ? last.close - prev.close : null,
    changePct: prev && prev.close ? (last.close / prev.close - 1) * 100 : null,
    high52: Math.max(...year.map((c) => c.high)),
    low52: Math.min(...year.map((c) => c.low)),
    volume: last.volume,
  }
}

const signedPct = (n: number | null) => (n == null ? '' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`)

function compact(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `${(n / 1e5).toFixed(2)} L`
  return inr(n, 0)
}

export default function Dashboard() {
  return (
    <BrainGate>
      <DashboardBody />
    </BrainGate>
  )
}

function DashboardBody() {
  const latest = useLatestRun()
  const run = latest.data!
  const [win, setWin] = useState<Window>('15d')
  const [picked, setPicked] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [sector, setSector] = useState('ALL')
  const [minScore, setMinScore] = useState(0)

  const picks = useMemo(
    () => ideasFrom(run).filter((d) => ['TRADE', 'WATCH'].includes(finalWord(d))),
    [run],
  )
  const symbols = picks.map((d) => d.symbol)

  const sectors = useQuery({
    queryKey: ['sectorNames', symbols.join(',')],
    queryFn: () => api.sectors(symbols),
    enabled: symbols.length > 0,
    retry: false,
  })
  const names = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist, retry: false })
  const nameOf = (sym: string) => names.data?.find((i) => i.tradingsymbol === sym)?.name ?? null

  const candleQs = useQueries({
    queries: symbols.map((s) => ({
      queryKey: ['candles', s, 260],
      queryFn: () => api.candles(s, 260),
      retry: false,
    })),
  })
  const quotes = new Map(symbols.map((s, i) => [s, quoteFrom(candleQs[i]?.data)]))
  const candlesOf = (s: string) => candleQs[symbols.indexOf(s)]?.data

  const sectorOptions = Array.from(new Set(Object.values(sectors.data ?? {}).filter((s): s is string => !!s))).sort()

  const rows = picks.filter((d) => {
    if (query && !d.symbol.toLowerCase().includes(query.toLowerCase())) return false
    if (sector !== 'ALL' && sectors.data?.[d.symbol.toUpperCase()] !== sector) return false
    if (minScore > 0 && (score(d) ?? -1) < minScore) return false
    return true
  })
  const filtersOn = query !== '' || sector !== 'ALL' || minScore > 0
  const reset = () => {
    setQuery('')
    setSector('ALL')
    setMinScore(0)
  }

  const active = WINDOWS.find((w) => w.id === win)!
  const selected = rows.find((d) => d.symbol === picked) ?? rows[0]

  return (
    <div className="tm-page tm-grid">
      <div className="tm-dash-top">
        <Card glow>
          <div className="tm-dash-hero">
            <div className="tm-dash-art">
              <BrainArt />
            </div>
            <div className="tm-dash-herotext">
              <h1 className="tm-dash-title">Today&apos;s Swing Picks</h1>
              <p className="tm-note">
                Curated by the TradeMind brain from market data, price patterns, sector strength and risk rules.
                From the run on {formatDateTime(run.started_at)}.
              </p>
            </div>
            <div className="tm-dash-tabs" role="tablist">
              {WINDOWS.map((w) => (
                <button
                  key={w.id}
                  role="tab"
                  aria-selected={w.id === win}
                  className={`tm-dash-tab tm-dash-tab-${w.id} ${w.id === win ? 'active' : ''}`}
                  onClick={() => setWin(w.id)}
                >
                  <strong>{w.title}</strong>
                  <span>{w.kind}</span>
                  <small>{w.live ? w.span : 'Not available yet'}</small>
                </button>
              ))}
            </div>
          </div>
        </Card>
        <Card title="How it works?">
          <ol className="tm-dash-how">
            <li>The brain studies the market and looks for opportunities.</li>
            <li>Picks are grouped by time window.</li>
            <li>Each pick has an entry, targets, a stop loss and its reasons.</li>
            <li>You review and decide. Nothing here places an order.</li>
          </ol>
        </Card>
      </div>

      <SummaryStrip run={run} picks={picks} />

      <Card>
        <div className="tm-toolbar tm-dash-filters">
          <div className="tm-dash-pilltabs" role="tablist">
            {WINDOWS.map((w) => (
              <button
                key={w.id}
                role="tab"
                aria-selected={w.id === win}
                className={w.id === win ? 'active' : ''}
                onClick={() => setWin(w.id)}
              >
                {w.title} ({w.live ? picks.length : '—'})
              </button>
            ))}
          </div>
          <span className="tm-spacer" />
          {active.live && (
            <>
              <input
                className="tm-input"
                placeholder="Search stock (e.g. INFY)"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search stock"
              />
              <select className="tm-select" value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector">
                <option value="ALL">All Sectors</option>
                {sectorOptions.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <select
                className="tm-select"
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                aria-label="Minimum ranking (a model ranking, not a chance)"
              >
                {MIN_SCORES.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              <button type="button" className="tm-btn" onClick={reset} disabled={!filtersOn}>
                Reset
              </button>
            </>
          )}
        </div>

        {!active.live ? (
          <div style={{ padding: '0.6rem 0.2rem' }}>
            <p>
              <strong>{active.title} picks are not available yet.</strong> The brain plans for a window of up to
              15 trading days. It has not been trained or tested for the {active.title.toLowerCase()} window, so
              there is no honest pick to show here, and TradeMind will not invent one.
            </p>
            <p className="tm-dim">Use the 15 Days tab for the brain&apos;s real picks.</p>
          </div>
        ) : (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Stock</th>
                  <th>Sector</th>
                  <th className="tm-right">Current price</th>
                  <th>Setup</th>
                  <th>Entry range</th>
                  <th title="Rule: sell half here">Target 1</th>
                  <th>Target 2</th>
                  <th>Stop loss</th>
                  <th className="tm-right" title="Estimated chance of +8% before −4%, from past results on unseen days">
                    Est. chance
                  </th>
                  <th>Timeframe</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((d, i) => {
                  const mid = entryMid(d)
                  const t1 = mid != null ? mid * (1 + FIRST_TARGET) : null
                  const q = quotes.get(d.symbol)
                  const situation = stockSituations(run, d.symbol).find((s) => !s.is_unknown && s.label !== 'unlabelled')
                  return (
                    <tr
                      key={d.id}
                      className={`tm-clickable ${selected?.id === d.id ? 'tm-dash-selected' : ''}`}
                      onClick={() => setPicked(d.symbol)}
                    >
                      <td className="tm-dim">{i + 1}</td>
                      <td className="tm-strong">
                        <span className="tm-flex" style={{ gap: '0.5rem', alignItems: 'center' }}>
                          <StockLogo symbol={d.symbol} />
                          {d.symbol}
                          <ActionPill action={finalWord(d) as Action} />
                        </span>
                      </td>
                      <td className="tm-dim">{sectors.data?.[d.symbol.toUpperCase()] ?? '—'}</td>
                      <td className="tm-right tm-num">{q ? money(q.price) : '—'}</td>
                      <td className="tm-dim">{situation?.label ?? '—'}</td>
                      <td className="tm-dim">{entryText(d)}</td>
                      <td className="tm-pos">
                        {money(t1)} <small>{t1 != null ? '+5.0%' : ''}</small>
                      </td>
                      <td className="tm-pos">
                        {money(d.target)} <small>{pct(mid, d.target)}</small>
                      </td>
                      <td className="tm-neg">
                        {money(d.stop)} <small>{pct(mid, d.stop)}</small>
                      </td>
                      <td className="tm-right tm-num" title={chanceTitle(d)}>
                        {chanceText(d)}
                      </td>
                      <td>
                        <span className="tm-dash-badge">{d.horizon_days}D</span>
                      </td>
                      <td>
                        <Link
                          className="tm-btn"
                          to={`/trademind/stock/${encodeURIComponent(d.symbol)}`}
                          onClick={(e) => e.stopPropagation()}
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  )
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={12} className="tm-dim" style={{ textAlign: 'center', padding: '1.5rem' }}>
                      {picks.length === 0
                        ? `No TRADE or WATCH idea in the latest run${run.banner.mode === 'NO_NEW_TRADES' ? ' — the market mode says no new buys today.' : '.'}`
                        : 'No pick matches these filters.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {active.live && selected && (
        <PickDetail
          decision={selected}
          company={nameOf(selected.symbol)}
          sector={sectors.data?.[selected.symbol.toUpperCase()] ?? null}
          candles={candlesOf(selected.symbol)}
        />
      )}

      <p className="tm-dim" style={{ fontSize: '0.76rem' }}>
        TradeMind is in practice mode: these are ideas to study, not advice, and nothing here places an order.
        Markets can move against any plan, and the stop loss limits the loss only if it is acted on.
      </p>
    </div>
  )
}

function SummaryStrip({ run, picks }: { run: BrainRun; picks: BrainDecision[] }) {
  const regime = useQuery({ queryKey: ['marketRegime'], queryFn: api.marketRegime })
  const nifty = useQuery({ queryKey: ['candles', 'NIFTY 50', 60], queryFn: () => api.candles('NIFTY 50', 60), retry: false })
  const nq = quoteFrom(nifty.data)
  const spark = (nifty.data ?? []).map((c) => ({ t: c.ts.slice(5, 10), v: c.close }))
  const mode = run.banner.mode
  const trendWord =
    regime.data?.regime === 'bullish' ? 'Bullish' : regime.data?.regime === 'bearish' ? 'Bearish' : 'Unclear'

  const scores = picks.map(chancePercent).filter((s): s is number => s != null)
  const avgScore = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null
  const topSectors = (run.sectors ?? [])
    .filter((s) => s.strength_20d != null)
    .sort((a, b) => (b.strength_20d ?? 0) - (a.strength_20d ?? 0))
    .slice(0, 3)
  const best = Math.max(0.0001, ...topSectors.map((s) => Math.abs(s.strength_20d ?? 0)))

  return (
    <div className="tm-grid tm-cols-5 tm-dash-strip">
      <Card title="Market View" sub="Today">
        <div className="tm-state-word" style={{ fontSize: '1.4rem' }}>
          {regime.data ? trendWord : '…'}
        </div>
        {mode && (
          <>
            <Tag tone={MARKET_TONE[mode] ?? 'blue'}>{MARKET_LABEL[mode]}</Tag>
            <p className="tm-note">{MARKET_PLAIN[mode]}</p>
          </>
        )}
      </Card>

      <Card title="NIFTY 50" sub="Market trend">
        {regime.isError && <p className="tm-dim">Could not load the NIFTY level.</p>}
        <div className="tm-big tm-num" style={{ fontSize: '1.5rem' }}>
          {nq ? inr(nq.price, 2) : regime.data?.nifty_close != null ? inr(regime.data.nifty_close, 2) : '—'}
        </div>
        {nq && nq.change != null && (
          <div className={nq.change >= 0 ? 'tm-pos tm-num' : 'tm-neg tm-num'}>
            {nq.change >= 0 ? '+' : ''}
            {inr(nq.change, 2)} ({signedPct(nq.changePct)})
          </div>
        )}
        {spark.length > 1 && <GlowArea data={spark} height={44} formatter={(v) => inr(v, 0)} />}
      </Card>

      <Card title="Top Sectors" sub="Strongest, last 20 days">
        {topSectors.length === 0 ? (
          <p className="tm-dim">No sector data in this run.</p>
        ) : (
          topSectors.map((s) => (
            <div key={s.sector} className="tm-dash-sector">
              <span>{s.name}</span>
              <Meter pct={(Math.abs(s.strength_20d ?? 0) / best) * 100} color="var(--tm-green)" />
              <span className={(s.strength_20d ?? 0) >= 0 ? 'tm-pos tm-num' : 'tm-neg tm-num'}>
                {(s.strength_20d ?? 0) >= 0 ? '+' : ''}
                {((s.strength_20d ?? 0) * 100).toFixed(1)}%
              </span>
            </div>
          ))
        )}
      </Card>

      <Card title="Estimated chance" sub="Average of today's picks">
        <div className="tm-flex" style={{ alignItems: 'center', gap: '0.9rem' }}>
          <Ring
            value={avgScore ?? 0}
            empty={avgScore == null}
            size={72}
            stroke={7}
            center={<span className="tm-ring-value">{avgScore ?? '—'}</span>}
          />
          <p className="tm-note">Based on how similar scores did on days the model had not seen. Not a promise.</p>
        </div>
      </Card>

      <Card title="Total Picks" sub="By window">
        <div className="tm-big tm-num" style={{ fontSize: '1.9rem' }}>
          {picks.length}
        </div>
        <div className="tm-dash-counts">
          <span>5D: —</span>
          <span>15D: {picks.length}</span>
          <span>30D: —</span>
          <span>3M: —</span>
        </div>
      </Card>
    </div>
  )
}

function PickDetail({
  decision: d,
  company,
  sector,
  candles,
}: {
  decision: BrainDecision
  company: string | null
  sector: string | null
  candles: Candle[] | undefined
}) {
  const [range, setRange] = useState<RangeId>('1M')
  const bars = RANGES.find((r) => r.id === range)!.bars
  const points = (candles ?? []).slice(-bars).map((c) => ({ t: c.ts.slice(5, 10), v: c.close }))
  const q = quoteFrom(candles)
  const word = finalWord(d)
  const mid = entryMid(d)
  const t1 = mid != null ? mid * (1 + FIRST_TARGET) : null
  const risks = [d.downgrade_reason, d.overrule_reason].filter((r): r is string => !!r)

  return (
    <div className="tm-grid tm-cols-3 tm-dash-detail">
      <Card
        glow
        title={
          <span className="tm-flex" style={{ gap: '0.6rem', alignItems: 'center' }}>
            <StockLogo symbol={d.symbol} />
            {d.symbol}
            {company ? ` – ${company}` : ''}
            <ActionPill action={word as Action} />
          </span>
        }
        sub={sector ?? undefined}
        action={
          <div className="tm-dash-ranges">
            {RANGES.map((r) => (
              <button key={r.id} className={r.id === range ? 'active' : ''} onClick={() => setRange(r.id)}>
                {r.id}
              </button>
            ))}
          </div>
        }
      >
        {q && (
          <div className="tm-dash-quote">
            <span className="tm-big tm-num">{money(q.price)}</span>
            {q.change != null && (
              <span className={q.change >= 0 ? 'tm-pos tm-num' : 'tm-neg tm-num'}>
                {q.change >= 0 ? '+' : ''}
                {inr(q.change, 2)} ({signedPct(q.changePct)})
              </span>
            )}
          </div>
        )}
        {!candles && <p className="tm-dim">Loading price…</p>}
        {points.length > 1 && <GlowArea data={points} height={190} axes domain={['dataMin', 'dataMax']} formatter={(v) => `₹${inr(v, 0)}`} />}
        {q && (
          <div className="tm-dash-setup">
            <div>
              <small>Volume</small>
              <strong>{compact(q.volume)}</strong>
            </div>
            <div>
              <small>52W high</small>
              <strong>{money(q.high52)}</strong>
            </div>
            <div>
              <small>52W low</small>
              <strong>{money(q.low52)}</strong>
            </div>
          </div>
        )}
      </Card>

      <div className="tm-grid">
        <Card title={`Trade setup (${d.horizon_days} days)`}>
          <div className="tm-dash-kv">
            <span>Entry range</span>
            <strong>{entryText(d)}</strong>
            <span>Target 1 (sell half)</span>
            <strong className="tm-pos">
              {money(t1)} {t1 != null ? '(+5.0%)' : ''}
            </strong>
            <span>Target 2</span>
            <strong className="tm-pos">
              {money(d.target)} {pct(mid, d.target) && `(${pct(mid, d.target)})`}
            </strong>
            <span>Stop loss</span>
            <strong className="tm-neg">
              {money(d.stop)} {pct(mid, d.stop) && `(${pct(mid, d.stop)})`}
            </strong>
            <span>Holding period</span>
            <strong>up to {d.horizon_days} trading days</strong>
            <span>Position size</span>
            <strong>{d.qty > 0 ? `${d.qty} shares, set by your risk rules` : 'As per your risk rules'}</strong>
          </div>
        </Card>

        <Card title="Why this pick?" sub={`Estimated chance ${chanceText(d)} of reaching the target first`}>
          {d.reasons.length === 0 && <p className="tm-dim">The brain gave no reasons for this one.</p>}
          {d.reasons.map((r, i) => (
            <CheckItem key={i} tone={wordTone(word)}>
              {r}
            </CheckItem>
          ))}
          {risks.length > 0 && (
            <>
              <div className="tm-strong" style={{ marginTop: '0.8rem' }}>
                Key risks
              </div>
              {risks.map((r, i) => (
                <CheckItem key={i} tone="warn">
                  {r}
                </CheckItem>
              ))}
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
