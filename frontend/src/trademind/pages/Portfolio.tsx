import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { BrainDecision, BrainRun, DetailedPosition } from '../../api/types'
import { holdingsFrom, useBrainStatus, useLatestRun } from '../live'
import { BrainOff, Card, CheckItem, Donut, GlowArea, Tag, inr, signed, toneClass } from '../ui'

// Same private copy as every other TradeMind screen (see Home.tsx) — the
// owner's overrule, if any, otherwise the brain's own word.
function finalWord(d: BrainDecision): string {
  return d.overruled_word ?? d.word
}

const HOLDING_TONE: Record<string, 'green' | 'blue' | 'amber' | 'red'> = {
  HOLD: 'green',
  MONITOR: 'blue',
  REDUCE: 'amber',
  EXIT: 'red',
}

const SUGGESTION_TONE: Record<string, 'warn' | 'neg'> = {
  MONITOR: 'warn',
  REDUCE: 'warn',
  EXIT: 'neg',
}

// Purely a colour wheel for the donut — never a data value, so cycling a
// fixed palette by rank is fine even though the sectors themselves are real.
const SECTOR_COLORS = ['#4f8cff', '#2ee68a', '#8b5cf6', '#e04fd6', '#ffb547', '#33d6ff', '#ff6b6b', '#38bdf8']

/** The brain's "whole portfolio" view plus the what-if form — kept together
 * since both live inside the same brain-dependent card. */
function BrainPortfolioCard({ run }: { run: BrainRun }) {
  const [plan, setPlan] = useState({ symbol: '', qty: '' })
  const whatIf = useMutation({
    mutationFn: () => api.brainWhatIf(plan.symbol, Number(plan.qty)),
  })
  const view = run.portfolio

  return (
    <Card title="Your Portfolio as a Whole" sub="What the brain sees when it looks at everything together">
      <div className="tm-rows">
        <div className="tm-row">
          <span className="tm-dim">Biggest position</span>
          <span className="tm-strong">
            {view.largest_position
              ? `${view.largest_position[0]} · ${(view.largest_position[1] * 100).toFixed(0)}%`
              : 'Nothing held'}
          </span>
        </div>
        <div className="tm-row">
          <span className="tm-dim">Biggest sector</span>
          <span className="tm-strong">
            {view.top_sector ? `${view.top_sector[0]} · ${(view.top_sector[1] * 100).toFixed(0)}%` : '—'}
          </span>
        </div>
        <div className="tm-row">
          <span className="tm-dim">Move together</span>
          <span className="tm-strong">
            {(view.holdings_moving_together ?? []).length === 0
              ? 'None'
              : view.holdings_moving_together!.map(([a, b]) => `${a} & ${b}`).join(', ')}
          </span>
        </div>
      </div>

      <form
        className="tm-flex tm-wrap"
        style={{ gap: '0.5rem', marginTop: '0.8rem' }}
        onSubmit={(e) => {
          e.preventDefault()
          whatIf.mutate()
        }}
      >
        <input
          className="tm-input"
          placeholder="Stock, e.g. TCS"
          value={plan.symbol}
          onChange={(e) => setPlan({ ...plan, symbol: e.target.value })}
        />
        <input
          className="tm-input"
          placeholder="Shares"
          inputMode="numeric"
          value={plan.qty}
          onChange={(e) => setPlan({ ...plan, qty: e.target.value })}
        />
        <button className="tm-btn" disabled={!plan.symbol || !Number(plan.qty) || whatIf.isPending}>
          {whatIf.isPending ? 'Checking…' : 'What if I buy this?'}
        </button>
      </form>
      {whatIf.isError && <p className="tm-dim">Could not check that trade right now.</p>}
      {whatIf.data && (
        <div className="tm-callout" style={{ marginTop: '0.6rem' }}>
          {whatIf.data.qty} × {whatIf.data.symbol} ≈ ₹{inr(whatIf.data.value, 0)} → {whatIf.data.symbol} would be{' '}
          {(whatIf.data.stock_share_after * 100).toFixed(0)}% of the portfolio
          {whatIf.data.sector_share_after != null
            ? `, ${whatIf.data.sector_name} ${(whatIf.data.sector_share_after * 100).toFixed(0)}%`
            : ''}
          , cash left ₹{inr(whatIf.data.cash_after, 0)}.
          {whatIf.data.warnings.length === 0 && ' Within your limits.'}
          {whatIf.data.warnings.map((w) => (
            <div key={w} className="tm-warn" style={{ marginTop: '0.3rem' }}>
              {w}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

export default function Portfolio() {
  const status = useBrainStatus()
  const latest = useLatestRun()
  const summary = useQuery({ queryKey: ['summary'], queryFn: () => api.summary() })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const riskLimits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits })
  const equity = useQuery({ queryKey: ['equityCurve'], queryFn: () => api.equityCurve() })

  const posBySymbol = useMemo(
    () => new Map((positions.data ?? []).map((p) => [p.symbol, p] as [string, DetailedPosition])),
    [positions.data],
  )

  const run = latest.data
  const holdings = run ? holdingsFrom(run) : []

  return (
    <div className="tm-page tm-grid">
      <div className="tm-grid tm-cols-3">
        <Card glow className="tm-span-2" title="Portfolio Overview">
          {summary.isLoading && <p className="tm-dim">Loading…</p>}
          {summary.isError && <p className="tm-dim">Could not load your portfolio value right now.</p>}
          {summary.data && (
            <div className="tm-flex" style={{ alignItems: 'flex-end', gap: '1.5rem' }}>
              <div style={{ minWidth: 220 }}>
                <div className="tm-big tm-num" style={{ fontSize: '2.2rem' }}>
                  ₹ {inr(summary.data.total_value, 0)}
                </div>
                <div className={`${toneClass(summary.data.total_pnl)} tm-num`} style={{ fontWeight: 600, marginTop: 4 }}>
                  {signed(summary.data.total_return_pct * 100)} (
                  {summary.data.total_pnl >= 0 ? '+' : '−'}₹{inr(Math.abs(summary.data.total_pnl), 0)})
                </div>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                {equity.isLoading && <p className="tm-dim">Loading history…</p>}
                {equity.isError && <p className="tm-dim">History is not available right now.</p>}
                {equity.data && equity.data.length >= 2 && (
                  <GlowArea
                    data={equity.data.map((p) => ({ t: p.date.slice(5), v: p.total_value }))}
                    height={130}
                    formatter={(v) => `₹${inr(v, 0)}`}
                  />
                )}
                {equity.data && equity.data.length < 2 && (
                  <p className="tm-dim">Not enough days of history yet to draw a chart.</p>
                )}
              </div>
            </div>
          )}
        </Card>
        <Card title="Account">
          {summary.isLoading && <p className="tm-dim">Loading…</p>}
          {summary.isError && <p className="tm-dim">Not available right now.</p>}
          {summary.data && (
            <div className="tm-rows">
              <div className="tm-row">
                <span className="tm-dim">Positions</span>
                <span className="tm-strong">{summary.data.open_positions}</span>
              </div>
              <div className="tm-row">
                <span className="tm-dim">Cash</span>
                <span className="tm-strong">₹{inr(summary.data.cash, 0)}</span>
              </div>
              <div className="tm-row">
                <span className="tm-dim">Today</span>
                <span className={`tm-strong ${toneClass(summary.data.day_pnl)}`}>
                  {signed(summary.data.day_pnl_pct * 100)}
                </span>
              </div>
              <div className="tm-row" title="Biggest fall from a high point">
                <span className="tm-dim">Max Drawdown</span>
                <span className="tm-strong tm-neg">−{(summary.data.max_drawdown_pct * 100).toFixed(1)}%</span>
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="tm-grid tm-cols-2">
        <Card title="Sector Allocation">
          {riskLimits.isLoading && <p className="tm-dim">Loading…</p>}
          {riskLimits.isError && <p className="tm-dim">Not available right now.</p>}
          {riskLimits.data && riskLimits.data.sectors.length === 0 && (
            <p className="tm-dim">Nothing held yet, so there is nothing to break down by sector.</p>
          )}
          {riskLimits.data && riskLimits.data.sectors.length > 0 && (
            <div className="tm-flex" style={{ gap: '1.4rem' }}>
              <Donut
                size={140}
                stroke={22}
                segments={riskLimits.data.sectors.map((s, i) => ({
                  pct: Math.round(s.pct_of_portfolio * 1000) / 10,
                  color: SECTOR_COLORS[i % SECTOR_COLORS.length]!,
                  name: s.sector,
                }))}
              />
              <div className="tm-legend" style={{ flex: 1 }}>
                {riskLimits.data.sectors.map((s, i) => (
                  <div key={s.sector} className="tm-legend-row" style={{ color: SECTOR_COLORS[i % SECTOR_COLORS.length]! }}>
                    <span>
                      <span className="tm-swatch" />
                      <span style={{ color: 'var(--tm-text)' }}>{s.sector}</span>
                    </span>
                    <span className="tm-strong tm-num">{(s.pct_of_portfolio * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>

        {status === 'off' && <BrainOff />}
        {status === 'loading' && (
          <Card title="Your Portfolio as a Whole">
            <p className="tm-dim">Connecting to the brain…</p>
          </Card>
        )}
        {status === 'error' && (
          <Card title="Your Portfolio as a Whole">
            <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
          </Card>
        )}
        {status === 'no-run' && (
          <Card title="Your Portfolio as a Whole">
            <p className="tm-dim">The brain has not run yet.</p>
          </Card>
        )}
        {status === 'live' && run && <BrainPortfolioCard run={run} />}
      </div>

      <div className="tm-grid tm-cols-2">
        <Card title="Holdings" sub="What you own right now, and what the brain thinks of each">
          {status === 'off' && <p className="tm-dim">The brain is switched off on this server.</p>}
          {status === 'loading' && <p className="tm-dim">Connecting to the brain…</p>}
          {status === 'error' && <p className="tm-dim">Something went wrong talking to the brain.</p>}
          {status === 'no-run' && <p className="tm-dim">The brain has not run yet.</p>}
          {status === 'live' && holdings.length === 0 && <p className="tm-dim">You are not holding anything right now.</p>}
          {status === 'live' && holdings.length > 0 && (
            <div className="tm-table-wrap">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>Stock</th>
                    <th className="tm-right">Qty</th>
                    <th className="tm-right">Avg price</th>
                    <th className="tm-right">Value</th>
                    <th className="tm-right">P&amp;L</th>
                    <th>Brain says</th>
                  </tr>
                </thead>
                <tbody>
                  {holdings.map((h) => {
                    const p = posBySymbol.get(h.symbol)
                    return (
                      <tr key={h.id}>
                        <td className="tm-strong">{h.symbol}</td>
                        <td className="tm-right tm-num">{p ? p.quantity : '—'}</td>
                        <td className="tm-right tm-num">{p ? `₹${inr(p.entry_price)}` : '—'}</td>
                        <td className="tm-right tm-num">{p ? `₹${inr(p.current_value, 0)}` : '—'}</td>
                        <td className={`tm-right tm-num ${p ? toneClass(p.unrealized_pnl) : ''}`}>
                          {p ? `${p.unrealized_pnl >= 0 ? '+' : '−'}₹${inr(Math.abs(p.unrealized_pnl), 0)}` : '—'}
                        </td>
                        <td>
                          <Tag tone={HOLDING_TONE[finalWord(h)] ?? 'blue'}>{finalWord(h)}</Tag>
                          {h.reasons[0] && <div className="tm-dim" style={{ fontSize: '0.75rem', marginTop: 2 }}>{h.reasons[0]}</div>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card glow title="Suggestions" sub="What the brain would change">
          {status === 'off' && <p className="tm-dim">The brain is switched off on this server.</p>}
          {status === 'loading' && <p className="tm-dim">Connecting to the brain…</p>}
          {status === 'error' && <p className="tm-dim">Something went wrong talking to the brain.</p>}
          {status === 'no-run' && <p className="tm-dim">The brain has not run yet.</p>}
          {status === 'live' &&
            (() => {
              const flagged = holdings.filter((h) => finalWord(h) !== 'HOLD')
              if (flagged.length === 0) {
                return <p className="tm-dim">Nothing to change — the brain has no suggestions for what you hold.</p>
              }
              return flagged.map((h) =>
                h.reasons[0] ? (
                  <CheckItem key={h.id} tone={SUGGESTION_TONE[finalWord(h)] ?? 'warn'}>
                    {h.symbol}: {h.reasons[0]}
                  </CheckItem>
                ) : null,
              )
            })()}
        </Card>
      </div>
    </div>
  )
}
