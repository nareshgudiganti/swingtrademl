import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import { formatDateTime } from '../../lib/format'
import { marketSituation, useBrainStatus, useEpisodes, useLatestRun } from '../live'
import { MARKET_LABEL, MARKET_PLAIN, MARKET_TONE } from '../vocab'
import { BrainOff, Card, NotConnected, Tag, inr } from '../ui'

const ROTATION: Record<string, string> = {
  leading: 'Leading — stronger for 1 and 3 months',
  improving: 'Improving — stronger this month',
  weakening: 'Weakening — slipping this month',
  lagging: 'Lagging — weaker for 1 and 3 months',
  unknown: 'Not enough history yet',
}

const REGIME_PLAIN: Record<string, string> = {
  bullish: 'Above its own trend — a rising market.',
  bearish: 'Below its own trend — a falling market.',
  unknown: 'Not enough data to judge the trend.',
}

export default function Market() {
  const status = useBrainStatus()
  const latest = useLatestRun()
  const episodes = useEpisodes()
  const regime = useQuery({ queryKey: ['marketRegime'], queryFn: api.marketRegime })

  if (status === 'off') return <div className="tm-page"><BrainOff /></div>

  if (status === 'loading') {
    return (
      <div className="tm-page">
        <p className="tm-dim">Connecting to the brain…</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tm-page">
        <Card title="Could not reach the brain">
          <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  if (status === 'no-run') {
    return (
      <div className="tm-page">
        <Card title="No run yet">
          <p className="tm-dim">The brain has not run yet.</p>
        </Card>
      </div>
    )
  }

  const run = latest.data!
  const situation = marketSituation(run)
  const sectors = run.sectors ?? []

  return (
    <div className="tm-page tm-grid">
      <div className="tm-grid tm-cols-3">
        <Card
          glow
          className="tm-span-2"
          title="Market Mode"
          sub={`From the brain's run on ${formatDateTime(run.started_at)}`}
        >
          <div className="tm-hero-state" style={{ minWidth: 200 }}>
            <div>
              <div className="tm-state-word" style={{ fontSize: '1.7rem' }}>
                {run.banner.mode ? MARKET_LABEL[run.banner.mode] : 'Unknown'}
              </div>
              {run.banner.mode && (
                <Tag tone={MARKET_TONE[run.banner.mode] ?? 'blue'}>{MARKET_PLAIN[run.banner.mode]}</Tag>
              )}
            </div>
          </div>
          {run.banner.headline && <p className="tm-note">{run.banner.headline}</p>}
          {situation && situation.label !== 'unlabelled' ? (
            <p className="tm-note">
              Situation: {situation.label}
              {situation.is_unknown ? ' — never seen before' : ''}
              {situation.evidence.length > 0 ? ` — ${situation.evidence.join('; ')}` : ''}
            </p>
          ) : (
            <p className="tm-dim">The brain did not recognise a named market situation today.</p>
          )}
        </Card>

        <Card title="NIFTY 50" sub="From the market data service">
          {regime.isLoading && <p className="tm-dim">Loading…</p>}
          {regime.isError && <p className="tm-dim">Could not load the NIFTY level.</p>}
          {regime.data && (
            <>
              <div className="tm-big tm-num" style={{ fontSize: '1.6rem' }}>
                {regime.data.nifty_close != null ? `${inr(regime.data.nifty_close, 0)} pts` : '—'}
              </div>
              <p className="tm-note">{REGIME_PLAIN[regime.data.regime] ?? REGIME_PLAIN.unknown}</p>
              <p className="tm-dim" style={{ fontSize: '0.78rem' }}>
                Volatility: {regime.data.volatility_level}
              </p>
            </>
          )}
        </Card>
      </div>

      <div className="tm-grid tm-cols-3">
        <Card className="tm-span-2" title="Sector Rotation" sub="Rank among all sectors, last 20 trading days">
          {sectors.length === 0 ? (
            <p className="tm-dim">No sector data in this run.</p>
          ) : (
            <div className="tm-table-wrap">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Sector</th>
                    <th>Direction</th>
                    <th className="tm-right">20-day strength</th>
                  </tr>
                </thead>
                <tbody>
                  {sectors.map((s) => (
                    <tr key={s.sector}>
                      <td className="tm-num">{s.rank}/{s.of_total}</td>
                      <td className="tm-strong">{s.name}</td>
                      <td className="tm-dim">{ROTATION[s.rotation] ?? s.rotation}</td>
                      <td className="tm-right tm-num">
                        {s.strength_20d == null ? '—' : `${s.strength_20d >= 0 ? '+' : ''}${(s.strength_20d * 100).toFixed(1)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <NotConnected
          what="Market Breadth"
          reason="How many stocks rose vs fell today is not connected yet — no endpoint reports it."
        />
      </div>

      <div className="tm-grid tm-cols-2">
        <Card title="Market History" sub="The stretches the market went through, as the brain names them">
          {episodes.isLoading && <p className="tm-dim">Loading…</p>}
          {episodes.isError && <p className="tm-dim">Could not load market history.</p>}
          {episodes.data && episodes.data.length === 0 && <p className="tm-dim">No history recorded yet.</p>}
          {episodes.data && episodes.data.length > 0 && (
            <div className="tm-table-wrap">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>Situation</th>
                    <th>From</th>
                    <th>To</th>
                    <th className="tm-right">NIFTY change</th>
                  </tr>
                </thead>
                <tbody>
                  {episodes.data.map((e) => (
                    <tr key={e.start_day}>
                      <td>{e.label}</td>
                      <td className="tm-dim">{e.start_day}</td>
                      <td className="tm-dim">{e.end_day ?? 'still going'}</td>
                      <td className="tm-right tm-num">
                        {e.nifty_change == null ? '—' : `${e.nifty_change >= 0 ? '+' : ''}${(e.nifty_change * 100).toFixed(1)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <NotConnected
          what="Fear Gauge (India VIX)"
          reason="The brain does not read the VIX index yet — only a volatility level, shown on the NIFTY card."
        />
      </div>
    </div>
  )
}
