import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, setApiKey } from '../api/client'
import { ErrorBox, Loading } from '../components/Loading'

export default function Settings() {
  const queryClient = useQueryClient()

  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })
  const coverage = useQuery({ queryKey: ['coverage'], queryFn: api.coverage })
  const telegram = useQuery({ queryKey: ['telegram'], queryFn: api.telegramStatus })

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
        <div className="card">
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
        <div className="card">
          <div className="stat-label">Zerodha session</div>
          <div className="stat-value">
            <span className={`badge ${s?.broker_authenticated ? 'badge-on' : 'badge-off'}`}>
              {s?.broker_authenticated ? 'connected' : 'not connected'}
            </span>
          </div>
          <div className="stat-sub">
            <a
              href="http://localhost:8000/api/v1/auth/kite/login"
              target="_blank"
              rel="noreferrer"
              style={{ textDecoration: 'underline' }}
            >
              Log in to Kite
            </a>{' '}
            — required every trading morning.
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Scheduler</div>
          <div className="stat-value">
            <span className={`badge ${s?.scheduler_running ? 'badge-on' : 'badge-off'}`}>
              {s?.scheduler_running ? 'running' : 'stopped'}
            </span>
          </div>
          <div className="stat-sub">{s?.scheduled_jobs.length ?? 0} jobs registered</div>
        </div>
      </div>

      {s?.scheduled_jobs.length ? (
        <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>Trigger</th>
                <th>Next run</th>
              </tr>
            </thead>
            <tbody>
              {s.scheduled_jobs.map((j) => (
                <tr key={j.id}>
                  <td>{j.id}</td>
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
          const raw = String(new FormData(event.currentTarget).get('symbols') ?? '')
          const symbols = raw
            .split(',')
            .map((x) => x.trim().toUpperCase())
            .filter(Boolean)
          if (symbols.length) saveWatchlist.mutate(symbols)
        }}
      >
        <div className="stat-label">NSE symbols, comma separated</div>
        <input
          name="symbols"
          defaultValue={watchlist.data?.map((i) => i.tradingsymbol).join(', ') ?? ''}
          placeholder="RELIANCE, TCS, INFY"
        />
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
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="row">
          <span className={`badge ${telegram.data?.ok ? 'badge-on' : 'badge-off'}`}>
            {telegram.data?.ok ? `@${telegram.data.bot}` : 'not configured'}
          </span>
          <button onClick={() => testTelegram.mutate()} disabled={testTelegram.isPending}>
            Send test message
          </button>
        </div>
        {telegram.data?.error && <p className="muted">{telegram.data.error}</p>}
        {testTelegram.data && <p className="muted">{testTelegram.data.message}</p>}
        {testTelegram.error && <ErrorBox error={testTelegram.error} />}
      </div>

      <h2>API key</h2>
      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault()
          const value = new FormData(event.currentTarget).get('key')
          if (typeof value === 'string' && value.trim()) {
            setApiKey(value)
            window.location.reload()
          }
        }}
      >
        <div className="stat-label">Replace the stored API key</div>
        <input name="key" type="password" placeholder="New API key" />
        <button className="primary" type="submit" style={{ marginTop: '0.8rem' }}>
          Save and reload
        </button>
      </form>
    </>
  )
}
