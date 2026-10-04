import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import { formatDate, formatDateTime } from '../../lib/format'
import { Confirm } from '../Confirm'
import { Card, PageHead, Tag } from '../ui'

type Dialog = 'halt' | 'resume' | 'refresh' | null

function Problem({ what }: { what: string }) {
  return <p className="tm-neg">Could not load {what}. Try again shortly.</p>
}

export default function Control() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const safety = useQuery({ queryKey: ['safetyState'], queryFn: api.safetyState })
  const [dialog, setDialog] = useState<Dialog>(null)
  const [loginError, setLoginError] = useState<string | null>(null)
  const close = () => setDialog(null)

  const s = status.data
  const halted = safety.data ? !safety.data.new_entries_enabled : false

  async function logIn() {
    setLoginError(null)
    try {
      const r = await api.kiteLogin()
      window.open(r.login_url, '_blank')
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : 'Could not start the login.')
    }
  }

  async function refreshPrices() {
    const data = await api.refreshData()
    queryClient.setQueryData(['status'], data)
    for (const key of ['signals', 'signalHistory', 'strategySignals', 'predictions']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
  }

  function afterSafetyChange() {
    void queryClient.invalidateQueries({ queryKey: ['safetyState'] })
    void queryClient.invalidateQueries({ queryKey: ['riskEvents'] })
    void queryClient.invalidateQueries({ queryKey: ['status'] })
  }

  return (
    <div className="tm-page">
      <PageHead title="Control" sub="Your control room: log in to Zerodha, update prices, and stop or allow new trades." />

      <div className="tm-grid tm-control">
        <Card title="Zerodha">
          {status.isLoading && <p className="tm-dim">Loading…</p>}
          {status.isError && <Problem what="the Zerodha status" />}
          {s && (
            <>
              <div className="tm-flex tm-control-row">
                <span className="tm-strong">Login</span>
                <Tag tone={s.broker_authenticated ? 'green' : 'amber'}>
                  {s.broker_authenticated ? 'Connected' : 'Not logged in'}
                </Tag>
              </div>
              <div className="tm-flex tm-control-row">
                <span className="tm-strong">Money being used</span>
                <Tag tone={s.trading_mode === 'live' ? 'red' : 'blue'}>
                  {s.trading_mode === 'live' ? 'Real money (live)' : 'Practice money (paper)'}
                </Tag>
              </div>
              <p className="tm-dim">
                The automatic login runs on weekday mornings. In practice mode, trades still go through at the last
                known price, but prices stop updating without a login.
              </p>
              {!s.broker_authenticated && (
                <button className="tm-btn" onClick={() => void logIn()}>
                  Log in to Zerodha
                </button>
              )}
              {loginError && <p className="tm-neg">{loginError}</p>}
            </>
          )}
        </Card>

        <Card title="Prices">
          {status.isLoading && <p className="tm-dim">Loading…</p>}
          {status.isError && <Problem what="the price information" />}
          {s && (
            <>
              <div className="tm-flex tm-control-row">
                <span className="tm-strong">Latest prices are from</span>
                <span>{s.latest_candle_date ? formatDate(s.latest_candle_date) : 'No prices yet'}</span>
              </div>
              <button className="tm-btn" onClick={() => setDialog('refresh')}>
                Refresh prices now
              </button>
            </>
          )}
        </Card>

        <Card title="New trades">
          {safety.isLoading && <p className="tm-dim">Loading…</p>}
          {safety.isError && <Problem what="whether new trades are allowed" />}
          {safety.data && (
            <>
              <div className="tm-flex tm-control-row">
                <span className="tm-strong">New buys</span>
                <Tag tone={halted ? 'red' : 'green'}>{halted ? 'Stopped' : 'Allowed'}</Tag>
              </div>
              {halted && (
                <p className="tm-dim">
                  Stopped{safety.data.halted_at ? ` on ${formatDateTime(safety.data.halted_at)}` : ''}
                  {safety.data.halted_by ? ` by ${safety.data.halted_by}` : ''}
                  {safety.data.halt_reason ? `: ${safety.data.halt_reason}` : '.'}
                </p>
              )}
              <p className="tm-dim">
                Stopping only blocks NEW buys. Stocks you already hold keep their normal stop-loss and target.
              </p>
              {halted ? (
                <button className="tm-btn" onClick={() => setDialog('resume')}>
                  Allow new trades again
                </button>
              ) : (
                <button className="tm-btn tm-btn-danger" onClick={() => setDialog('halt')}>
                  Stop new trades
                </button>
              )}
            </>
          )}
        </Card>
      </div>

      {dialog === 'refresh' && (
        <Confirm title="Refresh prices now?" confirmLabel="Refresh prices" onConfirm={refreshPrices} onClose={close}>
          This fetches the newest prices and updates the screens. It can take a little while.
        </Confirm>
      )}
      {dialog === 'halt' && (
        <Confirm
          title="Stop new trades?"
          confirmLabel="Stop new trades"
          danger
          reason={{ label: 'Why are you stopping?', placeholder: 'For example: going away this week' }}
          onConfirm={async (reason) => {
            await api.haltEntries(reason)
            afterSafetyChange()
          }}
          onClose={close}
        >
          No new stocks will be bought until you allow it again. Stocks you already hold keep their normal stop-loss
          and target.
        </Confirm>
      )}
      {dialog === 'resume' && (
        <Confirm
          title="Allow new trades again?"
          confirmLabel="Allow new trades"
          onConfirm={async () => {
            await api.resumeEntries()
            afterSafetyChange()
          }}
          onClose={close}
        >
          The bot may buy new stocks again, within your limits.
        </Confirm>
      )}
    </div>
  )
}
