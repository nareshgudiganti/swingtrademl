import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { BrainRun, DetailedPosition } from '../../api/types'
import { finalWord, holdingsFrom, useBrainStatus, useLatestRun } from '../live'
import { wordTone } from '../vocab'
import { Term, WordTag } from '../term'
import { BrainOff, Card, CheckItem, Donut, GlowArea, inr, signed, toneClass } from '../ui'
import { PageState, QueryNotice } from '../PageState'
import AddMoneyCard from '../AddMoney'
import { HoldingsHealthCard } from '../HoldingsHealth'
import { usePlan } from '../../lib/plan'
import { UpcomingEventsLive } from '../beginner/UpcomingEvents'
import { withoutScorePercent } from '../scoreText'

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
          <span className="tm-dim">
            Biggest <Term k="sector">sector</Term>
          </span>
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
  // The bot's held stocks are the owner's book: the server answers this list only for the owner.
  const { canManage } = usePlan()
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
        <Card glow className="tm-span-2" title="Portfolio Overview" sub="Paper figures: the bot's own practice book">
          <QueryNotice q={summary} what="your portfolio value" />
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
                {(summary.data.money_added ?? 0) > 0 && (
                  <p className="tm-dim" style={{ fontSize: 12, margin: '6px 0 0' }}>
                    Includes ₹{inr(summary.data.money_added ?? 0, 0)} you added, which is not counted as profit.
                    {summary.data.time_weighted_return_pct != null &&
                      ` The bot's own return, whatever the top-ups: ${signed(summary.data.time_weighted_return_pct * 100)}.`}
                  </p>
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <QueryNotice q={equity} what="the value history" />
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
          {summary.data === undefined && <QueryNotice q={summary} what="your account" />}
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
                <span className="tm-dim">
                  Max <Term k="drawdown">Drawdown</Term>
                </span>
                {(() => {
                  const ddPct = Math.round(summary.data.max_drawdown_pct * 1000) / 10
                  return (
                    <span className={`tm-strong ${ddPct > 0 ? 'tm-neg' : ''}`}>
                      {ddPct > 0 ? `−${ddPct.toFixed(1)}%` : '0%'}
                    </span>
                  )
                })()}
              </div>
              {summary.data.max_drawdown_label ? (
                <p className="tm-dim" style={{ fontSize: 11, margin: 0 }}>
                  {summary.data.max_drawdown_label}
                </p>
              ) : null}
            </div>
          )}
        </Card>
      </div>

      {canManage && <AddMoneyCard />}

      <div className="tm-grid tm-cols-2">
        <Card
          title={
            <>
              <Term k="sector">Sector</Term> Allocation
            </>
          }
        >
          <QueryNotice q={riskLimits} what="the sector split" />
          {riskLimits.data && riskLimits.data.sectors.length === 0 && (
            <PageState kind="empty" reason="Nothing held yet, so there is nothing to break down by sector." />
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
            <PageState kind="loading" what="the brain's view" />
          </Card>
        )}
        {status === 'error' && (
          <Card title="Your Portfolio as a Whole">
            <PageState kind="error" what="the brain's view" error={latest.error} onRetry={latest.refetch} />
          </Card>
        )}
        {status === 'no-run' && (
          <Card title="Your Portfolio as a Whole">
            <PageState kind="empty" reason="The brain has not finished a run yet, so it has no view of your portfolio." />
          </Card>
        )}
        {status === 'live' && run && <BrainPortfolioCard run={run} />}
      </div>

      <HoldingsHealthCard />

      <div className="tm-grid tm-cols-2">
        <Card title="Holdings" sub="What you own right now, and what the brain thinks of each">
          {status === 'off' && <p className="tm-dim">The brain is switched off on this server.</p>}
          {status === 'loading' && <PageState kind="loading" what="the brain's view" />}
          {status === 'error' && (
            <PageState kind="error" what="the brain's view" error={latest.error} onRetry={latest.refetch} />
          )}
          {status === 'no-run' && <PageState kind="empty" reason="The brain has not finished a run yet." />}
          {status === 'live' && holdings.length === 0 && (
            <PageState kind="empty" reason="The bot holds no paper shares in the brain's last run." />
          )}
          {status === 'live' && holdings.length > 0 && (
            <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>Stock</th>
                    <th className="tm-right">Qty</th>
                    <th className="tm-right">Avg price</th>
                    <th className="tm-right">Value</th>
                    <th className="tm-right">
                      <Term k="unrealised">P&amp;L</Term>
                    </th>
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
                          <WordTag word={finalWord(h)} />
                          {h.reasons[0] && <div className="tm-dim" style={{ fontSize: '0.75rem', marginTop: 2 }}>{withoutScorePercent(h.reasons[0])}</div>}
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
          {status === 'loading' && <PageState kind="loading" what="the brain's view" />}
          {status === 'error' && (
            <PageState kind="error" what="the brain's view" error={latest.error} onRetry={latest.refetch} />
          )}
          {status === 'no-run' && <PageState kind="empty" reason="The brain has not finished a run yet." />}
          {status === 'live' &&
            (() => {
              const flagged = holdings.filter((h) => finalWord(h) !== 'HOLD')
              if (flagged.length === 0) {
                return <p className="tm-dim">Nothing to change — the brain has no suggestions for what you hold.</p>
              }
              return flagged.map((h) =>
                h.reasons[0] ? (
                  <CheckItem key={h.id} tone={wordTone(finalWord(h))}>
                    {h.symbol}: {withoutScorePercent(h.reasons[0])}
                  </CheckItem>
                ) : null,
              )
            })()}
        </Card>
      </div>

      {canManage && (
        <Card title="Coming up for the stocks the bot holds" sub="Results and other company events in the next 15 trading days">
          <UpcomingEventsLive scope="held" />
        </Card>
      )}
    </div>
  )
}
