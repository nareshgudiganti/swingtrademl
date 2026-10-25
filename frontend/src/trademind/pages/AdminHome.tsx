// The new look's Admin home (owner only): is everything running, and which safety switches are on. Display only:
// every row is read from the server (/status, /market/session, /admin/jobs, /brain/health, /brain/stage,
// /safety/state, /risk/limits, and the real-orders switch for the real-account owner). It adds NO switch that
// changes behaviour: the buttons open the existing Control, Go-live and Jobs pages, whose actions already ask the
// owner to confirm. The route itself is owner-only (TradeMindApp.tsx), and the menu hides Admin from everyone else.

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import { usePlan } from '../../lib/plan'
import { formatDateTime } from '../../lib/format'
import { useMarketSession } from '../live'
import { istToday, pricesAge } from '../pricesAge'
import { adminStatusRows, type StatusTone } from '../wave3Rules'
import '../newlook-w3.css'

type Switch = { id: string; title: string; note: string; value: string; tone: StatusTone }

export default function AdminHome() {
  const { canSeeRealAccount } = usePlan()
  const status = useQuery({ queryKey: ['status'], queryFn: api.status, retry: false })
  const market = useMarketSession()
  const jobs = useQuery({ queryKey: ['admin-jobs'], queryFn: api.adminJobs, retry: false })
  const health = useQuery({ queryKey: ['brainHealth'], queryFn: api.brainHealth, retry: false })
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage, retry: false })
  const safety = useQuery({ queryKey: ['safetyState'], queryFn: api.safetyState, retry: false })
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits, retry: false })
  const realOrders = useQuery({
    queryKey: ['realOrdersStatus'],
    queryFn: api.realOrdersStatus,
    enabled: canSeeRealAccount,
    retry: false,
  })

  const m = market.data
  const age = m
    ? pricesAge({
        latestCandleDate: m.latest_candle_date ?? null,
        today: m.today ?? istToday(new Date()),
        recentClosedTradingDays: m.recent_closed_trading_days ?? [m.last_closed_trading_day],
      })
    : null

  const rows = adminStatusRows({
    status: status.data,
    pricesTone: age?.tone,
    pricesLabel: age?.label,
    jobs: jobs.data,
    jobsError: jobs.isError,
    stage: stage.data?.stage,
    brainLastOk: health.data ? health.data.last_nightly_ok : undefined,
    brainFailed7d: health.data?.failed_runs_7d,
  })
  const brainRow = rows.find((r) => r.id === 'brain')
  if (brainRow && health.data?.last_nightly_ok) brainRow.note = `Last good nightly run: ${formatDateTime(health.data.last_nightly_ok)}.${health.data.failed_runs_7d ? ` ${health.data.failed_runs_7d} failed in the last 7 days.` : ''}`

  const switches: Switch[] = []
  if (safety.data) {
    switches.push({
      id: 'entries',
      title: 'New buys by the bot',
      note: safety.data.new_entries_enabled
        ? 'Allowed, within the limits below.'
        : `Stopped${safety.data.halted_by ? ` by ${safety.data.halted_by}` : ''}${safety.data.halt_reason ? `: ${safety.data.halt_reason}` : ''}.`,
      value: safety.data.new_entries_enabled ? 'ALLOWED' : 'STOPPED',
      tone: safety.data.new_entries_enabled ? 'green' : 'red',
    })
    switches.push({
      id: 'exits',
      title: 'Automatic selling (stops and targets)',
      note: safety.data.exits_enabled ? 'Held stocks are sold on their stop or target.' : 'Automatic selling is switched off.',
      value: safety.data.exits_enabled ? 'ON' : 'OFF',
      tone: safety.data.exits_enabled ? 'green' : 'red',
    })
  }
  if (canSeeRealAccount && realOrders.data) {
    switches.push({
      id: 'real-orders',
      title: 'Buys and sells of my own Zerodha shares',
      note: 'Real money · each order still asks you to confirm.',
      value: realOrders.data.enabled ? 'ON' : 'OFF',
      tone: realOrders.data.enabled ? 'amber' : 'grey',
    })
  }
  if (status.data && status.data.paper_tester_enabled != null) {
    switches.push({
      id: 'tester',
      title: 'Manual paper testing',
      note: 'Practice buys by hand in the Testing tab.',
      value: status.data.paper_tester_enabled ? 'ON' : 'OFF',
      tone: status.data.paper_tester_enabled ? 'green' : 'grey',
    })
  }
  if (limits.data) {
    switches.push({
      id: 'drawdown',
      title: `Stop all new buys if the account falls ${Math.round(limits.data.max_drawdown_pct * 100)}%`,
      note: 'Measured from its highest value.',
      value: 'SET',
      tone: 'green',
    })
    if (limits.data.sector_rule === 'one_per_sector')
      switches.push({
        id: 'sector',
        title: 'At most one stock per sector',
        note: 'The rule for an account of this size.',
        value: 'SET',
        tone: 'green',
      })
    else if (limits.data.sector_cap_pct != null)
      switches.push({
        id: 'sector',
        title: `At most ${Math.round(limits.data.sector_cap_pct * 100)}% of the account in one sector`,
        note: 'No more than that share of the account in any one sector.',
        value: 'SET',
        tone: 'green',
      })
  }

  return (
    <div className="tm-page tmw3" data-page="admin-home">
      <div className="tmw3-head">
        <h2 className="tmw3-h1">
          Admin &amp; Safety <span className="tmw3-pill tmw3-pill-blue">Owner only</span>
        </h2>
        <p className="tm-dim">Is everything running, and which safety switches are on.</p>
      </div>

      <div className="tmn-row-2">
        <section className="tmn-card" aria-label="System status" data-testid="admin-status">
          <div className="tmn-card-head">
            <span className="tmn-card-title">System status</span>
            <Link className="tm-link tmn-small" to="/trademind/system">
              Full system page
            </Link>
          </div>
          {rows.map((r) => (
            <div key={r.id} className="tmw3-srow" data-row={r.id}>
              <span className="tmw3-grow">
                {r.label}
                {r.note && <span className="tmn-small tm-dim tmw3-block">{r.note}</span>}
              </span>
              <span className={`tmw3-badge tmw3-badge-${r.tone}`}>{r.value}</span>
            </div>
          ))}
        </section>

        <section className="tmn-card" aria-label="Safety switches" data-testid="admin-switches">
          <div className="tmn-card-head">
            <span className="tmn-card-title">Safety switches</span>
            <span className="tmn-small tm-dim">Live state, read only here</span>
          </div>
          {switches.length === 0 && <p className="tm-dim">Could not read the safety switches right now.</p>}
          {switches.map((s) => (
            <div key={s.id} className="tmw3-srow" data-row={s.id}>
              <span className="tmw3-grow">
                <b>{s.title}</b>
                <span className="tmn-small tm-dim tmw3-block">{s.note}</span>
              </span>
              <span className={`tmw3-badge tmw3-badge-${s.tone}`}>{s.value}</span>
            </div>
          ))}
          <div className="tmw3-actions">
            <Link className="tm-btn" to="/trademind/control">
              {safety.data && !safety.data.new_entries_enabled ? 'Allow new buys again…' : 'Stop all new buys…'}
            </Link>
            <Link className="tm-btn tm-btn-ghost" to="/trademind/golive">
              Trading stage
            </Link>
            <Link className="tm-btn tm-btn-ghost" to="/trademind/jobs">
              Nightly jobs
            </Link>
          </div>
          <p className="tmn-small tm-dim">
            The buttons open the control pages, where every change asks you to confirm. Nothing changes from this page.
          </p>
        </section>
      </div>
      <p className="tmn-small tm-dim">Only the owner can see this page. Going live with real money is the owner&apos;s decision only.</p>
    </div>
  )
}
