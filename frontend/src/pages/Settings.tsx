import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api, clearToken } from '../api/client'
import { ErrorBox, Loading } from '../components/Loading'
import SymbolPicker from '../components/SymbolPicker'
import { ClockIcon, PlugIcon, SendIcon, WarningIcon } from '../components/icons'

// Job IDs are stable (see workers/scheduler.py); their exact cron time isn't
// duplicated here on purpose — that's read live from `trigger`/`next_run`
// below, so this table can never silently drift out of sync with a schedule
// change. This is just the "what does this job do" a raw id doesn't convey.
const JOB_DESCRIPTIONS: Record<string, string> = {
  refresh_quotes: 'Pulls live prices during market hours and marks positions to market',
  check_exits: 'Enforces stop-loss/target on open positions — the safety net',
  reconcile_orders: 'Checks pending live orders against their real broker status',
  daily_ingest: "Pulls the day's final candle after the close",
  predict_watchlist: 'Scores the large-cap watchlist for the Recommendations page',
  signal_scan: 'The main daily scan — generates BUY/HOLD/EXIT signals for every strategy',
  daily_summary: 'Posts the end-of-day portfolio summary',
  evaluate_predictions: "Scores yesterday's predictions once their horizon has elapsed",
  sync_instruments: "Refreshes Kite's instrument list (weekly — nothing trades on Sunday)",
}

export default function Settings() {
  const queryClient = useQueryClient()

  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })
  const coverage = useQuery({ queryKey: ['coverage'], queryFn: api.coverage })
  const telegram = useQuery({ queryKey: ['telegram'], queryFn: api.telegramStatus })
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })

  const [symbols, setSymbols] = useState<string[]>([])
  const seeded = useRef(false)
  useEffect(() => {
    if (watchlist.data && !seeded.current) {
      setSymbols(watchlist.data.map((i) => i.tradingsymbol))
      seeded.current = true
    }
  }, [watchlist.data])

  const saveWatchlist = useMutation({
    mutationFn: (symbols: string[]) => api.setWatchlist(symbols),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
      queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })

  const sync = useMutation({ mutationFn: api.syncInstruments })
  const backfill = useMutation({ mutationFn: () => api.backfill({ interval: 'day' }) })
  const testTelegram = useMutation({ mutationFn: api.telegramTest })

  if (status.isLoading) return <Loading />

  const s = status.data

  return (
    <>
      <div className="page-head">
        <h1>Settings</h1>
      </div>

      <h2>System</h2>
      <div className="grid">
        <div className="card card-with-icon">
          <div>
            <div className="stat-label">Trading mode</div>
            <div className="stat-value">
              <span className={`badge ${s?.live_trading_enabled ? 'badge-live' : 'badge-paper'}`}>
                {s?.live_trading_enabled ? 'LIVE' : 'PAPER'}
              </span>
            </div>
            <div className="stat-sub">
              Change this in <code>.env</code> and restart. Live requires both{' '}
              <code>TRADING_MODE=live</code> and <code>ALLOW_LIVE_TRADING=true</code>.
            </div>
          </div>
          <div className={`icon-chip ${s?.live_trading_enabled ? 'chip-warn' : 'chip-accent'}`}>
            <WarningIcon />
          </div>
        </div>
        <div className="card card-with-icon">
          <div>
            <div className="stat-label">Zerodha session</div>
            <div className="stat-value">
              <span className={`badge ${s?.broker_authenticated ? 'badge-on' : 'badge-off'}`}>
                {s?.broker_authenticated ? 'connected' : 'not connected'}
              </span>
            </div>
            <div className="stat-sub">
              {!s?.broker_authenticated && s && s.open_positions > 0 ? (
                <strong>
                  Stop-loss/target checks are NOT running on your {s.open_positions} open position
                  {s.open_positions === 1 ? '' : 's'}.{' '}
                </strong>
              ) : null}
              <a
                href="#"
                onClick={(e) => {
                  e.preventDefault()
                  api.kiteLogin().then((r) => window.open(r.login_url, '_blank'))
                }}
                style={{ textDecoration: 'underline' }}
              >
                Log in to Kite
              </a>{' '}
              — required every trading morning, tokens expire ~06:00 IST.
            </div>
          </div>
          <div className={`icon-chip ${s?.broker_authenticated ? 'chip-accent' : 'chip-warn'}`}>
            <PlugIcon />
          </div>
        </div>
        <div className="card card-with-icon">
          <div>
            <div className="stat-label">Scheduler</div>
            <div className="stat-value">
              <span className={`badge ${s?.scheduler_running ? 'badge-on' : 'badge-off'}`}>
                {s?.scheduler_running ? 'running' : 'stopped'}
              </span>
            </div>
            <div className="stat-sub">{s?.scheduled_jobs.length ?? 0} jobs registered</div>
          </div>
          <div className="icon-chip chip-accent">
            <ClockIcon />
          </div>
        </div>
        <div className="card card-with-icon">
          <div>
            <div className="stat-label">Last scan</div>
            <div className="stat-value">
              {s?.last_scan_result ? (
                <span className={`badge ${s.last_scan_result.errors > 0 ? 'badge-warn' : 'badge-on'}`}>
                  {s.last_scan_result.buys} buy{s.last_scan_result.buys === 1 ? '' : 's'} found
                </span>
              ) : (
                <span className="badge badge-off">no data yet</span>
              )}
            </div>
            <div className="stat-sub">
              {s?.last_scan_result ? (
                <>
                  {new Date(s.last_scan_result.ts).toLocaleString('en-IN')} —{' '}
                  {s.last_scan_result.instruments_evaluated} symbols checked across{' '}
                  {s.last_scan_result.strategies_run} strateg{s.last_scan_result.strategies_run === 1 ? 'y' : 'ies'}
                  {s.last_scan_result.errors > 0 ? `, ${s.last_scan_result.errors} error(s)` : ''}.
                </>
              ) : (
                'Fills in after the next 15:45 IST scan.'
              )}
            </div>
          </div>
          <div className={`icon-chip ${s?.last_scan_result?.errors ? 'chip-warn' : 'chip-accent'}`}>
            <ClockIcon />
          </div>
        </div>
      </div>

      {s?.scheduled_jobs.length ? (
        <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>What it does</th>
                <th>Trigger</th>
                <th>Next run</th>
              </tr>
            </thead>
            <tbody>
              {s.scheduled_jobs.map((j) => (
                <tr key={j.id}>
                  <td className="mono">{j.id}</td>
                  <td>{JOB_DESCRIPTIONS[j.id] ?? <span className="muted">—</span>}</td>
                  <td className="muted">{j.trigger}</td>
                  <td className="muted">
                    {j.next_run ? new Date(j.next_run).toLocaleString('en-IN') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <h2>Watchlist</h2>
      <form
        className="card"
        style={{ marginBottom: '1.5rem' }}
        onSubmit={(event) => {
          event.preventDefault()
          if (symbols.length) saveWatchlist.mutate(symbols)
        }}
      >
        <div className="stat-label">NSE symbols — search by name or code</div>
        <SymbolPicker value={symbols} onChange={setSymbols} placeholder="Search RELIANCE, TCS, INFY…" />
        <div className="row" style={{ marginTop: '0.8rem' }}>
          <button className="primary" type="submit" disabled={saveWatchlist.isPending}>
            Save watchlist
          </button>
          <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}>
            Sync instruments from Kite
          </button>
          <button type="button" onClick={() => backfill.mutate()} disabled={backfill.isPending}>
            Backfill history
          </button>
        </div>
        {saveWatchlist.error && <ErrorBox error={saveWatchlist.error} />}
        {sync.data && <p className="muted">{sync.data.message}</p>}
        {backfill.data && <p className="muted">{backfill.data.message}. {backfill.data.detail}</p>}
      </form>

      <h2>Data coverage</h2>
      <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
        {!coverage.data?.length ? (
          <div className="empty">
            No candles ingested yet. Sync instruments, set a watchlist, then backfill.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Candles</th>
                <th>From</th>
                <th>To</th>
              </tr>
            </thead>
            <tbody>
              {coverage.data.map((c) => (
                <tr key={c.symbol}>
                  <td>
                    <strong>{c.symbol}</strong>
                  </td>
                  {/* Training needs ~300 usable rows after the 252-bar warm-up */}
                  <td className={`num ${c.candles < 300 ? 'neg' : ''}`}>
                    {c.candles.toLocaleString('en-IN')}
                  </td>
                  <td className="muted">{c.from ?? '—'}</td>
                  <td className="muted">{c.to ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Telegram</h2>
      <div className="card card-with-icon" style={{ marginBottom: '1.5rem' }}>
        <div style={{ width: '100%' }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className={`badge ${telegram.data?.ok ? 'badge-on' : 'badge-off'}`}>
              {telegram.data?.ok ? `@${telegram.data.bot}` : 'not configured'}
            </span>
            <button onClick={() => testTelegram.mutate()} disabled={testTelegram.isPending}>
              Send test message
            </button>
          </div>
          <div className="stat-sub" style={{ marginTop: '0.5rem' }}>
            {telegram.data?.ok
              ? 'EXIT signals and confidence-decay alerts push here — without it, they only ever show up if you open the dashboard.'
              : telegram.data?.error ?? 'Without this, EXIT signals and alerts are silent unless you check the dashboard yourself.'}
          </div>
          {testTelegram.data && <p className="muted" style={{ marginBottom: 0 }}>{testTelegram.data.message}</p>}
          {testTelegram.error && <ErrorBox error={testTelegram.error} />}
        </div>
        <div className={`icon-chip ${telegram.data?.ok ? 'chip-accent' : 'chip-warn'}`}>
          <SendIcon />
        </div>
      </div>

      <h2>Advanced</h2>
      <div className="grid" style={{ marginBottom: '1.5rem' }}>
        <Link to="/strategies" className="card card-with-icon" style={{ textDecoration: 'none', color: 'inherit' }}>
          <div>
            <div className="stat-label">Strategies</div>
            <div className="stat-sub">
              Configure how signals get generated and whether they auto-execute or are advisory only.
            </div>
          </div>
        </Link>
        <Link to="/models" className="card card-with-icon" style={{ textDecoration: 'none', color: 'inherit' }}>
          <div>
            <div className="stat-label">ML Models</div>
            <div className="stat-sub">Train, evaluate, and activate the models behind every signal.</div>
          </div>
        </Link>
      </div>

      <h2>Account</h2>
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div>
            <div className="stat-value" style={{ fontSize: '1.1rem' }}>
              {me.data?.username ?? '…'}
            </div>
            <div className="stat-sub">
              {me.data?.email ?? 'no email'} · signed in via {me.data?.auth_provider ?? '—'}
            </div>
          </div>
          <button
            className="danger"
            onClick={() => {
              clearToken()
              window.location.reload()
            }}
          >
            Log out
          </button>
        </div>
      </div>
    </>
  )
}
