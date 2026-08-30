import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api } from '../api/client'
import Stat from '../components/Stat'
import { ErrorBox, Loading } from '../components/Loading'
import {
  formatCompact,
  formatCurrency,
  formatDateTime,
  formatPercent,
  formatSignedPercent,
  pnlClass,
} from '../lib/format'

const EXIT_KIND: Record<string, { icon: string; label: string }> = {
  STOP_LOSS_HIT: { icon: '🔴', label: 'Stop-loss' },
  TARGET_HIT: { icon: '🟢', label: 'Target hit' },
}

export default function Dashboard() {
  const queryClient = useQueryClient()
  const summary = useQuery({ queryKey: ['summary'], queryFn: () => api.summary() })
  const equity = useQuery({ queryKey: ['equity'], queryFn: () => api.equityCurve(180) })
  const signals = useQuery({ queryKey: ['signals', 5], queryFn: () => api.latestSignals(5) })
  // Matches check_exits' own 60s cadence — no point polling faster than a
  // new exit could possibly appear, but this is what makes the "Recent
  // exits" card below actually live instead of only updating on page reload.
  const trades = useQuery({
    queryKey: ['trades', 50],
    queryFn: () => api.trades(50),
    refetchInterval: 60_000,
  })
  const regime = useQuery({ queryKey: ['marketRegime'], queryFn: api.marketRegime })
  const status = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: 30_000 })
  const refresh = useMutation({
    mutationFn: api.refreshData,
    onSuccess: (data) => {
      queryClient.setQueryData(['status'], data)
      queryClient.invalidateQueries({ queryKey: ['signals'] })
      queryClient.invalidateQueries({ queryKey: ['predictions'] })
      queryClient.invalidateQueries({ queryKey: ['strategySignals'] })
    },
  })

  if (summary.isLoading) return <Loading />
  if (summary.error) return <ErrorBox error={summary.error} />

  const s = summary.data!
  const r = regime.data
  const st = status.data

  return (
    <>
      <div className="page-head">
        <h1>Dashboard</h1>
        <div className="row" style={{ gap: '0.5rem' }}>
          <span className={`badge ${s.mode === 'live' ? 'badge-live' : 'badge-paper'}`}>
            {s.mode.toUpperCase()}
          </span>
          {r && r.regime !== 'unknown' && (
            <span className={`badge ${r.regime === 'bullish' ? 'badge-buy' : 'badge-sell'}`}>
              {r.regime.toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {st && (
        <div className={`banner ${st.status_level === 'ok' ? 'banner-ok' : 'banner-warn'}`}>
          {st.status_level === 'ok' ? '✅' : '⚠️'} {st.status_message}
          {st.status_level === 'warning' && st.broker_authenticated && (
            <>
              {' '}
              <a
                href="#"
                onClick={(e) => {
                  e.preventDefault()
                  if (!refresh.isPending) refresh.mutate()
                }}
                style={{ color: 'inherit', textDecoration: 'underline' }}
              >
                {refresh.isPending ? 'Refreshing…' : 'Refresh now'}
              </a>
              {refresh.isError && (
                <span> — {(refresh.error as Error)?.message ?? 'refresh failed'}</span>
              )}
            </>
          )}
        </div>
      )}

      <div className="grid">
        <Stat
          label="Portfolio value"
          value={formatCurrency(s.total_value)}
          sub={`Started at ${formatCompact(s.starting_capital)}`}
        />
        <Stat
          label="Total P&L"
          value={formatCurrency(s.total_pnl)}
          sub={formatSignedPercent(s.total_return_pct)}
          tone={pnlClass(s.total_pnl) as 'pos' | 'neg' | 'flat'}
        />
        <Stat
          label="Day P&L"
          value={formatCurrency(s.day_pnl)}
          sub={formatSignedPercent(s.day_pnl_pct)}
          tone={pnlClass(s.day_pnl) as 'pos' | 'neg' | 'flat'}
        />
        <Stat
          label="Cash"
          value={formatCurrency(s.cash)}
          sub={`${formatCurrency(s.holdings_value)} in holdings`}
        />
      </div>

      <div className="grid">
        <Stat label="Open positions" value={s.open_positions} sub={`${s.total_trades} closed`} />
        <Stat
          label="Win rate"
          value={formatPercent(s.win_rate, 1)}
          sub={`${s.winning_trades}W / ${s.losing_trades}L`}
        />
        <Stat
          label="Profit factor"
          value={Number.isFinite(s.profit_factor) ? s.profit_factor.toFixed(2) : '—'}
          sub={`Expectancy ${formatCurrency(s.expectancy)}/trade`}
        />
        <Stat
          label="Max drawdown"
          value={formatPercent(s.max_drawdown_pct)}
          sub={`Now ${formatPercent(s.current_drawdown_pct)}`}
          tone={s.current_drawdown_pct > 0.1 ? 'neg' : 'flat'}
        />
        <Stat label="Sharpe" value={s.sharpe_ratio.toFixed(2)} sub={`Sortino ${s.sortino_ratio.toFixed(2)}`} />
        <Stat
          label="Charges paid"
          value={formatCurrency(s.total_charges)}
          sub="Brokerage, taxes, slippage"
        />
      </div>

      <h2>Recent exits — stop-loss &amp; target hits</h2>
      <div className="card" style={{ marginBottom: '1.5rem', padding: '0.5rem 0' }}>
        {trades.isLoading ? (
          <Loading />
        ) : (
          (() => {
            const exits = (trades.data ?? [])
              .filter((t) => t.exit_reason === 'STOP_LOSS_HIT' || t.exit_reason === 'TARGET_HIT')
              .slice(0, 8)
            return !exits.length ? (
              <div className="empty">
                No stop-loss or target hits yet — this fills in the moment one fires. Telegram
                already pushes these the instant they happen; this is just the at-a-glance history.
              </div>
            ) : (
              exits.map((t) => {
                const kind = EXIT_KIND[t.exit_reason!] ?? { icon: '⚪', label: t.exit_reason }
                return (
                  <div
                    key={t.id}
                    className="row"
                    style={{
                      justifyContent: 'space-between',
                      padding: '0.6rem 1rem',
                      borderBottom: '1px solid var(--border)',
                    }}
                  >
                    <span className="row" style={{ gap: '0.6rem' }}>
                      <span>{kind.icon}</span>
                      <strong>{t.symbol}</strong>
                      <span className="muted">{kind.label}</span>
                    </span>
                    <span className="muted mono">
                      {formatCurrency(t.entry_price)} → {formatCurrency(t.exit_price)}
                    </span>
                    <span className={pnlClass(t.net_pnl)}>
                      {formatSignedPercent(t.return_pct)} ({formatCurrency(t.net_pnl)})
                    </span>
                    <span className="muted">{formatDateTime(t.exit_at)}</span>
                  </div>
                )
              })
            )
          })()
        )}
      </div>

      <h2>Equity curve</h2>
      <div className="card" style={{ height: 300, marginBottom: '1.5rem' }}>
        {equity.isLoading ? (
          <Loading />
        ) : !equity.data?.length ? (
          <div className="empty">
            No snapshots yet — the equity curve is recorded daily at 16:00 IST.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={equity.data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <defs>
                <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4f8cff" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#4f8cff" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#263352" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="date" stroke="#8b9bb4" fontSize={11} tickMargin={8} />
              <YAxis
                stroke="#8b9bb4"
                fontSize={11}
                width={70}
                tickFormatter={(v: number) => formatCompact(v)}
                // Starting capital is never zero, so a zero-based axis would
                // compress all the variation into a sliver at the top.
                domain={['auto', 'auto']}
              />
              <Tooltip
                contentStyle={{
                  background: '#131c31',
                  border: '1px solid #263352',
                  borderRadius: 10,
                }}
                formatter={(v: number) => formatCurrency(v)}
              />
              <Area
                type="monotone"
                dataKey="total_value"
                stroke="#4f8cff"
                strokeWidth={2}
                fill="url(#equityFill)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      <h2>Latest signals</h2>
      <div className="table-wrap">
        {signals.isLoading ? (
          <Loading />
        ) : !signals.data?.length ? (
          <div className="empty">No signals yet. Activate a strategy and run a scan.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Signal</th>
                <th className="num">Price</th>
                <th className="num">Confidence</th>
                <th>Status</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {signals.data.map((sig) => (
                <tr key={sig.id}>
                  <td>
                    <strong>{sig.symbol}</strong>
                  </td>
                  <td>
                    <span className={`badge badge-${sig.signal.toLowerCase()}`}>{sig.signal}</span>
                  </td>
                  <td className="num">{formatCurrency(sig.price)}</td>
                  <td className="num">
                    {sig.confidence !== null ? formatPercent(sig.confidence, 1) : '—'}
                  </td>
                  <td>
                    <span className={`badge ${sig.executed ? 'badge-on' : 'badge-off'}`}>
                      {sig.executed ? 'executed' : 'not taken'}
                    </span>
                  </td>
                  <td className="reason muted" title={sig.rejection_reason ?? sig.reason ?? ''}>
                    {sig.rejection_reason ?? sig.reason ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
