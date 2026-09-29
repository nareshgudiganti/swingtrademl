import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { PlanPick } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import TierBadge from '../components/TierBadge'
import { formatCurrency, formatDate, formatPercent } from '../lib/format'
import { PLAN_LABELS, usePlan } from '../lib/plan'
import { TIERS, tierFor } from '../lib/tiers'

// The home screen for Free / Plus / Pro users. Everything on it is shared
// market research, never the owner's own account: today's picks, the market
// mood, and — when the plan includes it — a budget split. Each section shows
// only if the plan has its feature; the API refuses it otherwise anyway.

const CAP_LABEL: Record<string, string> = { large: 'Large Cap', midcap: 'Mid Cap', smallcap: 'Small Cap' }

function pctFrom(price: number | null, level: number | null): number | null {
  return price && level ? (level - price) / price : null
}

function MarketMood() {
  const regime = useQuery({ queryKey: ['marketRegime'], queryFn: api.marketRegime })
  if (regime.isLoading) return <Loading label="Reading the market…" />
  if (regime.isError) return <ErrorBox error={regime.error} />
  const r = regime.data
  if (!r || r.regime === 'unknown') return <Empty label="The market mood isn't available yet today." />

  const rising = r.regime === 'bullish'
  const shaky = r.volatility_level === 'elevated'
  return (
    <div className="card">
      <div className="section-label">Market mood</div>
      <div className="row">
        <span className={`badge badge-lg ${rising ? 'badge-buy' : 'badge-sell'}`}>
          {rising ? 'Rising' : 'Falling'}
        </span>
        {shaky && <span className="badge badge-warn">Big daily swings</span>}
      </div>
      <p className="muted" style={{ margin: '0.6rem 0 0' }}>
        {rising
          ? 'The overall market (NIFTY 50) is in an uptrend. Buy signals tend to work better in a rising market.'
          : 'The overall market (NIFTY 50) is in a downtrend. Most stocks fall with it, so the model asks for more confidence before it says buy.'}
        {shaky && ' Prices are moving more than usual day to day, so expect bigger ups and downs.'}
      </p>
    </div>
  )
}

function PickCard({ pick }: { pick: PlanPick }) {
  const tier = tierFor(pick.strategy_name) ?? TIERS.find((t) => t.label === CAP_LABEL[pick.cap_tier]) ?? null
  const upside = pctFrom(pick.price, pick.take_profit)
  const downside = pctFrom(pick.price, pick.stop_loss)
  return (
    <div className="card">
      <div className="between">
        <div>
          <strong style={{ fontSize: '1.1rem' }}>{pick.symbol}</strong>
          {pick.name && <div className="muted" style={{ fontSize: '0.82rem' }}>{pick.name}</div>}
        </div>
        {tier && <TierBadge tier={tier} />}
      </div>
      <div style={{ display: 'grid', gap: '0.3rem', margin: '0.8rem 0' }}>
        <div className="between">
          <span className="muted">Buy around</span>
          <strong>{pick.price != null ? formatCurrency(pick.price) : '—'}</strong>
        </div>
        <div className="between">
          <span className="muted">Target (sell for a profit)</span>
          <span className="pos">
            {pick.take_profit != null ? formatCurrency(pick.take_profit) : '—'}
            {upside != null && ` (+${formatPercent(upside, 1)})`}
          </span>
        </div>
        <div className="between">
          <span className="muted">Stop-loss (sell to limit a loss)</span>
          <span className="neg">
            {pick.stop_loss != null ? formatCurrency(pick.stop_loss) : '—'}
            {downside != null && ` (${formatPercent(downside, 1)})`}
          </span>
        </div>
        <div className="between">
          <span className="muted">How sure the model is</span>
          <strong>{pick.confidence != null ? formatPercent(pick.confidence, 0) : '—'}</strong>
        </div>
        {pick.horizon_days != null && (
          <div className="between">
            <span className="muted">Expected to play out within</span>
            <span>{pick.horizon_days} trading days</span>
          </div>
        )}
      </div>
      {pick.reason && <div className="note">{pick.reason}</div>}
      <div className="muted" style={{ fontSize: '0.75rem', marginTop: '0.5rem' }}>
        Picked on {formatDate(pick.generated_at)}
      </div>
    </div>
  )
}

function BudgetSplit() {
  const [budget, setBudget] = useState(50_000)
  const split = useQuery({
    queryKey: ['topPicks', budget],
    queryFn: () => api.topPicks(budget),
    enabled: budget > 0,
  })
  return (
    <>
      <h2>Split a budget across today's picks</h2>
      <div className="row" style={{ marginBottom: '0.75rem' }}>
        <label htmlFor="budget" className="muted">
          Amount to invest (₹)
        </label>
        <input
          id="budget"
          type="number"
          min={1000}
          step={1000}
          value={budget}
          onChange={(e) => setBudget(Math.max(0, Number(e.target.value)))}
          style={{ maxWidth: 160 }}
        />
      </div>
      {split.isLoading && <Loading />}
      {split.isError && <ErrorBox error={split.error} />}
      {split.data && split.data.length === 0 && <Empty label="No pick is strong enough to size today." />}
      {split.data && split.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th>
                <th className="num">Price</th>
                <th className="num">Shares</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {split.data.map((p) => (
                <tr key={p.symbol}>
                  <td>{p.symbol}</td>
                  <td className="num">{p.price != null ? formatCurrency(p.price) : '—'}</td>
                  <td className="num">{p.suggested_quantity}</td>
                  <td className="num">{formatCurrency(p.suggested_allocation_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ fontSize: '0.8rem' }}>
        Stocks with a closer stop-loss get a bigger share, so each one risks about the same amount. This is a
        planning tool based only on the amount you typed.
      </p>
    </>
  )
}

export default function PlanHome() {
  const { plan, has } = usePlan()
  const picks = useQuery({ queryKey: ['picks'], queryFn: api.picks, enabled: has('picks') })
  const baseOnly = !has('all_models')
  const limit = plan?.limits.picks_per_day

  return (
    <>
      <div className="page-head">
        <div>
          <h1 style={{ marginBottom: '0.15rem' }}>Today's picks</h1>
          <div className="muted" style={{ fontSize: '0.82rem' }}>
            {PLAN_LABELS[plan?.plan ?? 'free']} plan
            {baseOnly && ' · from our Large Cap model'}
            {limit ? ` · top ${limit} a day` : ''}
          </div>
        </div>
      </div>

      {has('regime') && (
        <div style={{ marginBottom: '1.5rem' }}>
          <MarketMood />
        </div>
      )}

      {has('picks') && (
        <>
          {picks.isLoading && <Loading />}
          {picks.isError && <ErrorBox error={picks.error} />}
          {picks.data && picks.data.length === 0 && (
            <Empty label="No stock passed today. The model only says buy when it's confident, so some days have none." />
          )}
          {picks.data && picks.data.length > 0 && (
            <div className="grid">
              {picks.data.map((p) => (
                <PickCard key={p.symbol} pick={p} />
              ))}
            </div>
          )}
        </>
      )}

      {has('sizing') && <BudgetSplit />}

      <h2>How these picks are made</h2>
      <div className="card">
        <p style={{ marginTop: 0 }}>
          {baseOnly
            ? 'Every pick comes from our Large Cap model, which looks only at bigger, steadier companies.'
            : 'Picks come from our Large, Mid and Small Cap models.'}{' '}
          After the market closes each weekday, the model studies each stock's recent price and trading
          volume and estimates how likely it is to rise to its target before it falls to its stop-loss.
        </p>
        <p className="muted" style={{ marginBottom: 0 }}>
          It only says buy when that chance is high enough, and asks for more when the overall market is
          falling. Every past pick is kept on record, wins and losses alike.
        </p>
      </div>

      <p className="muted" style={{ fontSize: '0.75rem', marginTop: '1.5rem' }}>
        Generated by our machine-learning models for research purposes. Not a guarantee of returns. Please
        consider your own risk before acting.
      </p>
    </>
  )
}
