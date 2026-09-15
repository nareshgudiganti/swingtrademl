import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { Strategy, StrategyPerformance } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import SymbolPicker from '../components/SymbolPicker'
import TierBadge from '../components/TierBadge'
import { formatDate, formatPercent } from '../lib/format'
import { TIERS, tierFor } from '../lib/tiers'
import { riskLabelFor, type RiskLabel } from '../lib/strategyRisk'

const RISK_BADGE_CLASS: Record<RiskLabel, string> = {
  Conservative: 'badge-buy',
  Moderate: 'badge-hold',
  Aggressive: 'badge-sell',
}

const MIN_TRADES_FOR_RECOMMENDATION = 10

function ExecutionIcon({ auto }: { auto: boolean }) {
  return auto ? (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
      <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z" fill="currentColor" />
    </svg>
  ) : (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
      <path
        d="M9 11V6a2 2 0 0 1 4 0v5M13 6a2 2 0 0 1 4 0v6M17 8a2 2 0 0 1 4 0v6c0 3.3-2.7 6-6 6h-2a6 6 0 0 1-5-2.7L4 12"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** One cap-tier strategy card — the "which strategy should I use" view a
 * non-expert user actually wants, plain English first, numbers second. */
function StrategyCard({
  strategy,
  performance,
  isRecommended,
  recommendationReason,
  onToggle,
  toggling,
}: {
  strategy: Strategy
  performance: StrategyPerformance | undefined
  isRecommended: boolean
  recommendationReason: string | null
  onToggle: () => void
  toggling: boolean
}) {
  const tier = tierFor(strategy.name)
  const risk = riskLabelFor({ ...strategy.params, stop_loss_pct: strategy.stop_loss_pct ?? strategy.params.stop_loss_pct })
  const w90 = performance?.windows.last_90d
  const wAll = performance?.windows.all_time
  const hasEnoughData = (wAll?.trades ?? 0) >= MIN_TRADES_FOR_RECOMMENDATION
  const shownWindow = w90 && w90.trades >= 3 ? w90 : wAll

  return (
    <div className="card" style={{ position: 'relative' }}>
      {isRecommended && (
        <div
          className="badge badge-buy"
          style={{ position: 'absolute', top: '0.75rem', right: '0.75rem' }}
          title={recommendationReason ?? undefined}
        >
          Recommended
        </div>
      )}
      <div className="row" style={{ gap: '0.4rem', marginBottom: '0.4rem' }}>
        {tier && <TierBadge tier={tier} />}
        <span className={`badge ${RISK_BADGE_CLASS[risk.label]}`}>{risk.label}</span>
      </div>
      <h3 style={{ margin: '0 0 0.25rem' }}>{strategy.name}</h3>
      {tier && (
        <p className="muted" style={{ fontSize: '0.85rem', margin: '0 0 0.6rem' }}>
          {tier.description}
        </p>
      )}
      <div style={{ fontSize: '0.85rem', marginBottom: '0.6rem' }}>
        Watching <strong>{(performance?.universe_size ?? strategy.symbols.length) || '—'}</strong> stocks
        {performance ? `, ${performance.open_positions} held right now` : ''}.
      </div>
      <div style={{ fontSize: '0.85rem', marginBottom: '0.6rem' }}>
        {!shownWindow || shownWindow.trades === 0 ? (
          <span className="muted">No closed trades yet — check back after a few.</span>
        ) : hasEnoughData ? (
          <>
            Won <strong>{formatPercent(shownWindow.win_rate, 0)}</strong> of {shownWindow.trades} recent trades.
          </>
        ) : (
          <span className="muted">
            {wAll?.trades ?? 0} closed trade{(wAll?.trades ?? 0) === 1 ? '' : 's'} so far — needs{' '}
            {MIN_TRADES_FOR_RECOMMENDATION - (wAll?.trades ?? 0)} more before a reliable win rate shows.
          </span>
        )}
      </div>
      <button onClick={onToggle} disabled={toggling}>
        {strategy.is_active ? 'Deactivate' : 'Activate'}
      </button>
      <span className={`badge ${strategy.is_active ? 'badge-on' : 'badge-off'}`} style={{ marginLeft: '0.5rem' }}>
        {strategy.is_active ? 'active' : 'inactive'}
      </span>
    </div>
  )
}

export default function Strategies() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [symbols, setSymbols] = useState<string[]>([])

  const strategies = useQuery({ queryKey: ['strategies'], queryFn: api.strategies })
  const performance = useQuery({ queryKey: ['strategyPerformance'], queryFn: api.strategyPerformance })
  const types = useQuery({ queryKey: ['strategyTypes'], queryFn: api.strategyTypes })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })

  const openCountByStrategy = useMemo(() => {
    const counts = new Map<number, number>()
    for (const p of positions.data ?? []) {
      if (p.strategy_id == null) continue
      counts.set(p.strategy_id, (counts.get(p.strategy_id) ?? 0) + 1)
    }
    return counts
  }, [positions.data])

  const performanceById = useMemo(
    () => new Map((performance.data?.strategies ?? []).map((p) => [p.id, p])),
    [performance.data],
  )

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['strategies'] })
    queryClient.invalidateQueries({ queryKey: ['strategyPerformance'] })
  }

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      active ? api.deactivateStrategy(id) : api.activateStrategy(id),
    onSuccess: invalidate,
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteStrategy(id),
    onSuccess: invalidate,
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.createStrategy(body),
    onSuccess: () => {
      invalidate()
      setShowForm(false)
      setSymbols([])
    },
  })

  const scan = useMutation({
    mutationFn: api.scanAll,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['signals'] })
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      queryClient.invalidateQueries({ queryKey: ['summary'] })
    },
  })

  if (strategies.isLoading) return <Loading />
  if (strategies.error) return <ErrorBox error={strategies.error} />

  const rows = strategies.data ?? []
  const capTierRows = TIERS.map((tier) => rows.find((s) => s.name === tier.match)).filter(
    (s): s is Strategy => !!s,
  )
  const advancedRows = rows.filter((s) => !TIERS.some((t) => t.match === s.name))
  const recommendedId = performance.data?.recommended_strategy_id ?? null

  return (
    <>
      <div className="page-head">
        <h1>Strategies</h1>
        <div className="row">
          <button onClick={() => scan.mutate()} disabled={scan.isPending}>
            {scan.isPending ? 'Scanning…' : 'Run scan now'}
          </button>
          <button className="primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Cancel' : 'New strategy'}
          </button>
        </div>
      </div>

      <p className="muted" style={{ marginTop: 0 }}>
        Each card below is a trading approach the bot can run. Activating one only affects new
        picks going forward — anything already bought keeps running under whatever strategy
        picked it.
      </p>

      {scan.data && (
        <div className="banner banner-info">
          Scan complete — {scan.data.instruments_evaluated} instruments evaluated,{' '}
          {scan.data.signals_generated} signals ({scan.data.buys} buys, {scan.data.exits} exits),{' '}
          {scan.data.executed} executed
          {scan.data.errors.length > 0 && `, ${scan.data.errors.length} errors`}.
        </div>
      )}
      {(create.error || toggle.error || remove.error || scan.error) && (
        <ErrorBox error={create.error ?? toggle.error ?? remove.error ?? scan.error} />
      )}

      {showForm && (
        <form
          className="card"
          style={{ marginBottom: '1.5rem' }}
          onSubmit={(event) => {
            event.preventDefault()
            const form = new FormData(event.currentTarget)
            create.mutate({
              name: String(form.get('name')),
              strategy_type: String(form.get('strategy_type')),
              description: String(form.get('description') || ''),
              symbols,
              params: {},
            })
          }}
        >
          <h2>New strategy</h2>
          <div className="grid" style={{ marginBottom: '0.8rem' }}>
            <label>
              <div className="stat-label">Name</div>
              <input name="name" required placeholder="ML Swing — large caps" />
            </label>
            <label>
              <div className="stat-label">Type</div>
              <select name="strategy_type" required>
                {types.data?.map((t) => (
                  <option key={t.strategy_type} value={t.strategy_type}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <div className="stat-label">Symbols (blank = whole watchlist)</div>
              <SymbolPicker
                value={symbols}
                onChange={setSymbols}
                placeholder="Search INFY, TCS, RELIANCE…"
              />
            </label>
            <label>
              <div className="stat-label">Description</div>
              <input name="description" placeholder="Optional" />
            </label>
          </div>
          <button className="primary" type="submit" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
          <p className="muted" style={{ fontSize: '0.82rem' }}>
            New strategies start inactive. Review the parameters, then activate.
          </p>
        </form>
      )}

      {!capTierRows.length ? (
        <Empty label="No cap-tier strategies configured yet." />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', marginBottom: '1.5rem' }}>
          {capTierRows.map((s) => (
            <StrategyCard
              key={s.id}
              strategy={s}
              performance={performanceById.get(s.id)}
              isRecommended={recommendedId === s.id}
              recommendationReason={performance.data?.recommendation_reason ?? null}
              onToggle={() => toggle.mutate({ id: s.id, active: s.is_active })}
              toggling={toggle.isPending}
            />
          ))}
        </div>
      )}

      <details>
        <summary style={{ cursor: 'pointer', marginBottom: '0.75rem' }}>
          Advanced strategies ({advancedRows.length})
        </summary>
        <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
          {!advancedRows.length ? (
            <Empty label="No other strategies configured." />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Universe</th>
                  <th>Execution</th>
                  <th>Mode</th>
                  <th>Status</th>
                  <th className="num">Open</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {advancedRows.map((s) => {
                  const openCount = openCountByStrategy.get(s.id) ?? 0
                  return (
                    <tr key={s.id}>
                      <td>
                        <strong>{s.name}</strong>
                        {s.description && (
                          <div className="muted" style={{ fontSize: '0.75rem' }}>
                            {s.description}
                          </div>
                        )}
                      </td>
                      <td className="muted">{s.strategy_type}</td>
                      <td className="muted" title={s.symbols.length ? s.symbols.join(', ') : undefined}>
                        {s.symbols.length ? `${s.symbols.length} symbols` : 'full watchlist'}
                      </td>
                      <td>
                        <span
                          className="row"
                          style={{ gap: '0.35rem', color: 'var(--text-dim)', fontSize: '0.85rem' }}
                          title={
                            s.strategy_type !== 'long_term_value' && s.execution_mode === 'auto'
                              ? 'Places real orders automatically on a signal'
                              : 'Only recommends — you record the fill yourself'
                          }
                        >
                          <ExecutionIcon auto={s.strategy_type !== 'long_term_value' && s.execution_mode === 'auto'} />
                          {s.strategy_type === 'long_term_value' ? 'advisory' : s.execution_mode}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${s.mode === 'live' ? 'badge-live' : 'badge-paper'}`}>
                          {s.mode}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${s.is_active ? 'badge-on' : 'badge-off'}`}>
                          {s.is_active ? 'active' : 'inactive'}
                        </span>
                      </td>
                      <td className="num mono">{openCount}</td>
                      <td className="muted">{formatDate(s.created_at)}</td>
                      <td>
                        <div className="row">
                          <button
                            onClick={() => toggle.mutate({ id: s.id, active: s.is_active })}
                            disabled={toggle.isPending}
                          >
                            {s.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                          {!s.is_active && (
                            <button
                              className="danger"
                              onClick={() => confirm(`Delete "${s.name}"?`) && remove.mutate(s.id)}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        <h2>Available strategy types</h2>
        <div className="grid">
          {types.data?.map((t) => (
            <div className="card" key={t.strategy_type}>
              <div className="stat-label">{t.strategy_type}</div>
              <div style={{ fontWeight: 600, marginBottom: '0.35rem' }}>{t.display_name}</div>
              <p className="muted" style={{ fontSize: '0.82rem', margin: 0 }}>
                {t.description}
              </p>
            </div>
          ))}
        </div>
      </details>
    </>
  )
}
