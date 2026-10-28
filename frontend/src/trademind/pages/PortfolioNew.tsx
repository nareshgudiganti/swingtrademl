// The new look's Portfolio: one screen for the bot's paper book (it replaces the classic Paper Overview and Holdings
// Health). Top to bottom: the money, the holding that needs a decision, tonight's read on every held stock, the
// holdings health check, room for new trades, the safety net, sectors against the cap, and the value chart last.
// Display only: nothing here buys, sells or changes a stop, a size or a limit. The Bot / Testing / My Zerodha tabs
// stay in the sidebar as before. Every number is the server's or the brain's (portfolioRules.ts says how).

import { useState } from 'react'
import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { ApiError, api } from '../../api/client'
import type { BrainRun, CurrentLimits, DetailedPosition, EquityPoint, PortfolioSummary } from '../../api/types'
import { CapFlag, useSymbolCaps } from '../cap'
import { noTradeReason } from '../emptyReasons'
import AddMoneyCard from '../AddMoney'
import { HoldingsHealthCard } from '../HoldingsHealth'
import { currentDrawdownPct } from '../live-system'
import { ideasFrom, useLatestRun } from '../live'
import { QueryNotice } from '../PageState'
import {
  heldRows,
  moneyFigures,
  moneyRoom,
  pointsInRange,
  RULE_STATE_LABEL,
  safetyRules,
  sectorBars,
  wordSummary,
  type ChartRange,
  type HeldRow,
} from '../portfolioRules'
import { withoutScorePercent } from '../scoreText'
import { WordTag } from '../term'
import { wordTagColor } from '../vocab'
import { holdingsNeedingAttention } from '../today/HoldingsNeedsYou'
import { stoppedByRoom } from '../today/answerRules'
import { ideaCounts } from '../today/TodayIdeas'
import { SortTh, useSort } from '../sort'
import { GlowArea, inr, StockLogo, Tag } from '../ui'
import '../newlook-w2.css'

/** A server refusal for this account (not a failure): said once, quietly. */
function refused(q: { error: unknown }): boolean {
  return q.error instanceof ApiError && (q.error.status === 403 || q.error.status === 401)
}

export default function PortfolioNew({ owner = false }: { owner?: boolean }) {
  const latest = useLatestRun()
  const run = latest.data
  const summary = useQuery({ queryKey: ['summary'], queryFn: () => api.summary(), retry: false })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions, retry: false })
  // Owner-only answers: the account's limits, the stop switch. The server refuses them to everyone else anyway.
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits, enabled: owner, retry: false })
  const safety = useQuery({ queryKey: ['safetyState'], queryFn: api.safetyState, enabled: owner, retry: false })
  const status = useQuery({ queryKey: ['status'], queryFn: api.status, retry: false })
  const equity = useQuery({ queryKey: ['equityCurve', 400], queryFn: () => api.equityCurve(400), retry: false })

  const rows = heldRows(positions.data, run)
  const attention = run ? holdingsNeedingAttention(run) : []
  const ddPct = owner && equity.data ? currentDrawdownPct(equity.data) : null

  return (
    <div className="tm-page tmn-w2" data-page="portfolio-new">
      <div className="tmn-w2-head">
        <div>
          <h2 className="tmn-w2-h1">
            {owner ? 'My Portfolio' : 'Bot portfolio'} <Tag tone="blue">Paper</Tag>
          </h2>
          <p className="tm-dim tmn-w2-intro">
            {owner
              ? 'The bot’s paper money, whether there is room for more, and tonight’s read on every stock it holds.'
              : 'The bot’s paper portfolio, read only: its money, the room for new trades and tonight’s read on every stock it holds.'}
          </p>
        </div>
      </div>

      <Money summary={summary} />

      {attention.length > 0 && (
        <div className="tmn-w2-attn-list" data-testid="needs-decision">
          {attention.map((d) => (
            <Link key={d.id} to={`/trademind/stock/${encodeURIComponent(d.symbol)}`} className="tmn-w2-attn">
              <StockLogo symbol={d.symbol} />
              <span className="tmn-grow">
                <b>{d.symbol} needs a decision.</b>{' '}
                <span className="tm-dim">
                  The brain says {d.overruled_word ?? d.word}
                  {d.reasons[0] ? `: ${withoutScorePercent(d.reasons[0])}` : '.'}
                </span>
              </span>
              {/* A plain tag: the explaining WordTag is a button, which must not sit inside a link. */}
              <span className={`tm-tag tm-tag-${wordTagColor(d.overruled_word ?? d.word)}`}>{d.overruled_word ?? d.word}</span>
            </Link>
          ))}
        </div>
      )}

      <HeldTable rows={rows} positionsLoaded={positions.data !== undefined} positionsRefused={refused(positions)} runLoaded={!!run} />

      {owner && <AddMoneyCard />}

      <HoldingsHealthCard />

      <div className="tmn-w2-grid2">
        <Room owner={owner} run={run} limits={limits.data} />
        <section className="tmn-card" aria-label="Safety net" data-testid="safety-net">
          <div className="tmn-card-head">
            <span className="tmn-card-title">Safety net</span>
            <span className="tm-dim tmn-small">The rules every trade follows</span>
          </div>
          <ul className="tmn-w2-rules">
            {safetyRules({
              limits: owner ? limits.data : undefined,
              safety: owner ? safety.data : undefined,
              ddPct,
              status: status.data,
            }).map((r) => (
              <li key={r.key} className="tmn-w2-rule" data-key={r.key}>
                <span className="tmn-grow">
                  {r.text}
                  {r.detail && <span className="tm-dim tmn-small tmn-w2-sub">{r.detail}</span>}
                </span>
                <span className="tmn-w2-state" data-state={r.state}>
                  {RULE_STATE_LABEL[r.state]}
                </span>
              </li>
            ))}
          </ul>
          {!owner && (
            <p className="tm-dim tmn-small">
              The account’s own limits and its current fall from its peak are shown to the owner only.
            </p>
          )}
        </section>
      </div>

      <Sectors owner={owner} limits={limits.data} positions={positions.data} total={summary.data?.total_value ?? null} />

      <ValueChart equity={equity} />
    </div>
  )
}

function Money({ summary }: { summary: UseQueryResult<PortfolioSummary> }) {
  if (!summary.data) {
    if (refused(summary)) {
      return (
        <section className="tmn-card">
          <p className="tm-dim">The bot’s money figures are not included for your account.</p>
        </section>
      )
    }
    return (
      <section className="tmn-card">
        <QueryNotice q={summary} what="the portfolio" />
      </section>
    )
  }
  const m = moneyFigures(summary.data)
  return (
    <div className="tmn-w2-stats" data-testid="money">
      <div className="tmn-card">
        <div className="tmn-w2-stat">₹{inr(m.total, 0)}</div>
        <div className="tm-dim tmn-small">Total value · Paper</div>
      </div>
      <div className="tmn-card">
        <div className="tmn-w2-stat">{m.investedPct == null ? '—' : `${m.investedPct}%`}</div>
        <div className="tm-dim tmn-small">Invested · ₹{inr(m.invested, 0)}</div>
      </div>
      <div className="tmn-card">
        <div className="tmn-w2-stat">{m.investedPct == null ? '—' : `${100 - m.investedPct}%`}</div>
        <div className="tm-dim tmn-small">Cash · ₹{inr(m.cash, 0)}</div>
      </div>
      <div className="tmn-card">
        <div className="tmn-w2-stat">{m.held}</div>
        <div className="tm-dim tmn-small">{m.held === 1 ? 'Stock held' : 'Stocks held'}</div>
      </div>
    </div>
  )
}

function HeldTable({
  rows,
  positionsLoaded,
  positionsRefused,
  runLoaded,
}: {
  rows: HeldRow[]
  positionsLoaded: boolean
  positionsRefused: boolean
  runLoaded: boolean
}) {
  const caps = useSymbolCaps()
  const { sorted, sorter } = useSort(rows, {
    stock: (r: HeldRow) => r.symbol,
    qty: (r: HeldRow) => r.position?.quantity,
    price: (r: HeldRow) => r.position?.current_price,
    pnl: (r: HeldRow) => r.position?.unrealized_pnl_pct,
    tonight: (r: HeldRow) => r.word,
    score: (r: HeldRow) => r.score,
  }, { key: null }, { stock: 'asc', tonight: 'asc' })
  const summaryLine = wordSummary(rows)
  return (
    <section className="tmn-card tmn-w2-tablecard" aria-label="Your stocks" data-testid="held-table">
      <div className="tmn-card-head tmn-w2-pad">
        <span className="tmn-card-title">
          {positionsLoaded ? 'Your stocks' : 'The bot’s stocks'} — tonight’s read <Tag tone="blue">Paper</Tag>
        </span>
        {summaryLine && <span className="tm-dim tmn-small">{summaryLine}</span>}
      </div>
      {rows.length === 0 ? (
        <p className="tm-dim tmn-w2-empty" data-state="empty">
          {positionsLoaded || runLoaded ? 'The bot holds no paper shares right now.' : 'The held stocks could not be loaded.'}
        </p>
      ) : (
        <div className="tmn-w2-tablebox" role="region" aria-label="Table, scroll sideways to see more" tabIndex={0}>
          <table className="tmn-w2-table">
            <thead>
              <tr>
                <SortTh sorter={sorter} k="stock">Stock</SortTh>
                {positionsLoaded && <SortTh sorter={sorter} k="qty" right>Qty</SortTh>}
                {positionsLoaded && <SortTh sorter={sorter} k="price" right>Price</SortTh>}
                {positionsLoaded && <SortTh sorter={sorter} k="pnl" right>Gain / loss</SortTh>}
                <SortTh sorter={sorter} k="tonight">Tonight</SortTh>
                <th>Why, in a few words</th>
                {positionsLoaded && (
                  <SortTh
                    sorter={sorter}
                    k="score"
                    title="How strongly the model likes the stock today, out of 100. A ranking number, not a chance of profit. The change is since the previous daily reading."
                  >
                    Score
                  </SortTh>
                )}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const p = r.position
                return (
                  <tr key={r.symbol}>
                    <td>
                      <Link to={`/trademind/stock/${encodeURIComponent(r.symbol)}`} className="tmn-w2-stock">
                        <StockLogo symbol={r.symbol} />
                        <span>
                          <b>{r.symbol}</b> <CapFlag tier={p?.cap_tier ?? caps.get(r.symbol.toUpperCase())} />
                        </span>
                      </Link>
                    </td>
                    {positionsLoaded && <td className="tmn-w2-r">{p ? p.quantity : '—'}</td>}
                    {positionsLoaded && <td className="tmn-w2-r">{p ? `₹${inr(p.current_price)}` : '—'}</td>}
                    {positionsLoaded && (
                      <td className={`tmn-w2-r ${p ? (p.unrealized_pnl >= 0 ? 'tm-pos' : 'tm-neg') : ''}`}>
                        {p ? (
                          <>
                            {p.unrealized_pnl_pct >= 0 ? '+' : '−'}
                            {Math.abs(p.unrealized_pnl_pct * 100).toFixed(1)}%
                            <span className="tmn-small tmn-w2-sub">
                              {p.unrealized_pnl >= 0 ? '+' : '−'}₹{inr(Math.abs(p.unrealized_pnl), 0)}
                            </span>
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                    )}
                    <td>{r.word ? <WordTag word={r.word} /> : <span className="tm-dim tmn-small">Not read tonight</span>}</td>
                    <td className="tmn-w2-why">{r.why ?? <span className="tm-dim">—</span>}</td>
                    {positionsLoaded && (
                      <td>
                        {r.score == null ? (
                          <span className="tm-dim tmn-small">No score yet</span>
                        ) : (
                          <>
                            <b>{r.score}</b>
                            {r.change != null && r.change !== 0 && (
                              <span className={`tmn-small ${r.change > 0 ? 'tm-pos' : 'tm-neg'}`}>
                                {' '}
                                {r.change > 0 ? '▲' : '▼'}
                                {Math.abs(r.change)}
                              </span>
                            )}
                          </>
                        )}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {positionsRefused && (
        <p className="tm-dim tmn-small tmn-w2-pad">Quantities and prices are not included for your account; the brain’s read is.</p>
      )}
    </section>
  )
}

/** Room for new trades: the money room (owner: the server's numbers) and, for everyone, what the run says. */
function Room({ owner, run, limits }: { owner: boolean; run: BrainRun | undefined; limits: CurrentLimits | undefined }) {
  const room = owner ? moneyRoom(limits) : null
  const ideas = run ? ideasFrom(run) : []
  const tradeCount = run ? ideaCounts(run).TRADE : 0
  const blocked = stoppedByRoom(ideas)
  const reason = run ? noTradeReason(run.banner, ideas.length, tradeCount) : null
  const full = room ? room.limiting && room.room <= 0 : null
  return (
    <section className="tmn-card tmn-w2-room" data-full={full ? 'true' : undefined} aria-label="Room for new trades" data-testid="room">
      <div className="tmn-card-head">
        <span className="tmn-card-title">Room for new trades</span>
        {full != null && <span className="tmn-w2-state" data-state={full ? 'paused' : 'on'}>{full ? 'No money room' : 'Room left'}</span>}
      </div>
      {room && (
        <>
          {room.limiting ? (
            <p>
              Money room: in this market ({room.regime.toLowerCase()}) the bot may have at most <b>{room.limitPct}%</b> of
              the account invested (₹{inr(room.ceiling, 0)}). It has ₹{inr(room.invested, 0)} invested, so{' '}
              {room.room > 0 ? <>₹{inr(room.room, 0)} is left for new buys.</> : <>new buys wait.</>}
            </p>
          ) : (
            <p>The market is not limiting how much is invested right now ({room.regime.toLowerCase()}).</p>
          )}
          {room.limiting && room.ceiling > 0 && (
            <>
              <div className="tmn-w2-track" aria-label={`${Math.round((room.invested / room.ceiling) * 100)}% of the money room used`}>
                <span style={{ width: `${Math.min(100, Math.max(0, (room.invested / room.ceiling) * 100))}%` }} />
              </div>
              <div className="tm-dim tmn-small tmn-w2-ends">
                <span>Invested ₹{inr(room.invested, 0)}</span>
                <span>Limit ₹{inr(room.ceiling, 0)}</span>
              </div>
            </>
          )}
          {limits && (
            <p className="tm-dim tmn-small">
              {limits.open_positions} of {limits.max_positions} stock places in use at this account size.
            </p>
          )}
        </>
      )}
      {reason && <p className={room ? 'tm-dim tmn-small' : undefined}>{reason}</p>}
      {blocked > 0 && (
        <p className="tm-dim tmn-small">
          On the brain’s last run, {blocked === 1 ? '1 stock was' : `${blocked} stocks were`} stopped by the account’s safety limits.
        </p>
      )}
      {!room && !reason && blocked === 0 && (
        <p className="tm-dim">{run ? 'The brain’s last run found nothing held back by the account’s limits.' : 'The brain’s last run is not available.'}</p>
      )}
    </section>
  )
}

function Sectors({
  owner,
  limits,
  positions,
  total,
}: {
  owner: boolean
  limits: CurrentLimits | undefined
  positions: DetailedPosition[] | undefined
  total: number | null
}) {
  const one = limits?.sector_rule === 'one_per_sector'
  const bars = sectorBars(
    owner && limits
      ? { exposures: limits.sectors, capPct: limits.sector_cap_pct }
      : { positions, total },
  )
  if (bars.length === 0) return null
  const cap = owner && limits?.sector_cap_pct != null ? Math.round(limits.sector_cap_pct * 100) : 25
  return (
    <section className="tmn-card" aria-label="Invested by sector" data-testid="sectors">
      <div className="tmn-card-head">
        <span className="tmn-card-title">Invested by sector</span>
        <span className="tm-dim tmn-small">{one ? 'One stock per sector at this account size' : `Bars measured against the ${cap}% limit`}</span>
      </div>
      {bars.map((b) => (
        <div key={b.sector} className="tmn-w2-bar">
          <span>{b.sector}</span>
          <div className="tmn-w2-track" data-over={b.over ? 'true' : undefined}>
            <span style={{ width: `${one ? Math.min(100, b.pct) : b.ofCap}%` }} />
          </div>
          <b>{b.pct.toFixed(0)}%</b>
        </div>
      ))}
    </section>
  )
}

function ValueChart({ equity }: { equity: UseQueryResult<EquityPoint[]> }) {
  const [range, setRange] = useState<ChartRange>('1M')
  const points = equity.data ? pointsInRange(equity.data, range) : []
  return (
    <section className="tmn-card" aria-label="Total value over time" data-testid="value-chart">
      <div className="tmn-card-head">
        <span className="tmn-card-title">
          Total value over time <Tag tone="blue">Paper</Tag>
        </span>
        <div className="tmn-w2-range" role="group" aria-label="How far back">
          {(['1M', '3M', 'ALL'] as ChartRange[]).map((r) => (
            <button key={r} type="button" className={range === r ? 'on' : ''} aria-pressed={range === r} onClick={() => setRange(r)}>
              {r === 'ALL' ? 'Since start' : r}
            </button>
          ))}
        </div>
      </div>
      {equity.data === undefined ? (
        refused(equity) ? (
          <p className="tm-dim">The value history is not included for your account.</p>
        ) : (
          <QueryNotice q={equity} what="the value history" />
        )
      ) : points.length >= 2 ? (
        <GlowArea data={points.map((p) => ({ t: p.date.slice(5, 10), v: p.total_value }))} height={150} formatter={(v) => `₹${inr(v, 0)}`} />
      ) : (
        <p className="tm-dim">Not enough days of history yet to draw a chart.</p>
      )}
    </section>
  )
}
