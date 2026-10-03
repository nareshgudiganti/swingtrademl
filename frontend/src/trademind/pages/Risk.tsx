import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import { biggestSector, currentDrawdownPct, drawdownChartSeries, refusedDecisions } from '../live-system'
import { useBrainStatus, useLatestRun } from '../live'
import { BrainOff, Card, CheckItem, GlowArea, Meter, NotConnected, Ring, inr } from '../ui'

// `hard` marks a check that actually stops new trades outright (the kill
// switch, the drawdown halt, the market saying no new buys, or the broker
// being disconnected) — as opposed to a soft limit like a sector cap, which
// still allows trading. The headline card uses this split so it never says
// "allowed" while a hard stop is in force (F2).
type Check = { name: string; ok: boolean; note?: string; hard?: boolean }

export default function Risk() {
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits })
  const equity = useQuery({ queryKey: ['equityCurve', 400], queryFn: () => api.equityCurve(400) })
  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const safety = useQuery({ queryKey: ['safetyState'], queryFn: api.safetyState })
  const brainStatus = useBrainStatus()
  const latest = useLatestRun()

  if (limits.isLoading) {
    return (
      <div className="tm-page">
        <p className="tm-dim">Loading risk limits…</p>
      </div>
    )
  }

  if (limits.isError || !limits.data) {
    return (
      <div className="tm-page">
        <Card title="Could not load risk limits">
          <p className="tm-dim">Something went wrong talking to the risk service. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  const d = limits.data
  const points = equity.data ?? []
  const ddPct = currentDrawdownPct(points)
  const haltPct = d.max_drawdown_pct * 100
  const big = biggestSector(d.sectors)
  const deployedPct = d.deployable_ceiling_inr > 0 ? (d.invested_inr / d.deployable_ceiling_inr) * 100 : 0
  const cashPct = d.portfolio_value > 0 ? (d.cash / d.portfolio_value) * 100 : 0

  // The headline card waits for every input it judges to settle, so it
  // never has to guess "ALL CLEAR" before it actually knows (F2).
  const inputsLoading = status.isLoading || safety.isLoading || equity.isLoading || brainStatus === 'loading'

  const checks: Check[] = []
  checks.push({
    name: 'Open positions',
    ok: d.open_positions <= d.max_positions,
    note:
      d.open_positions > d.max_positions
        ? `${d.open_positions} open against a limit of ${d.max_positions}`
        : undefined,
  })
  if (d.sector_cap_pct != null && big) {
    const overCap = big.pct_of_portfolio >= d.sector_cap_pct
    checks.push({
      name: 'Sector limit',
      ok: !overCap,
      note: overCap
        ? `${big.sector} is ${(big.pct_of_portfolio * 100).toFixed(0)}% — over the ${(d.sector_cap_pct * 100).toFixed(0)}% limit`
        : undefined,
    })
  }
  checks.push({
    name: 'Cash floor',
    ok: d.cash >= d.cash_floor_inr,
    note: d.cash < d.cash_floor_inr ? `₹${inr(d.cash, 0)} free, below the ₹${inr(d.cash_floor_inr, 0)} floor` : undefined,
  })
  if (ddPct != null) {
    checks.push({
      name: 'Drawdown halt',
      ok: ddPct < haltPct,
      note: ddPct >= haltPct ? `${ddPct.toFixed(1)}% below peak — at the ${haltPct.toFixed(0)}% halt level` : undefined,
      hard: true,
    })
  }
  if (status.data) {
    checks.push({
      name: 'Broker connected',
      ok: status.data.broker_authenticated,
      note: status.data.broker_authenticated ? undefined : 'Zerodha is not connected — no trade can be placed.',
      hard: true,
    })
  }
  if (brainStatus === 'live' && latest.data) {
    const mode = latest.data.banner.mode
    checks.push({
      name: 'Market allows new trades',
      ok: mode !== 'NO_NEW_TRADES',
      note: mode === 'NO_NEW_TRADES' ? latest.data.banner.headline ?? 'New buys are paused today.' : undefined,
      hard: true,
    })
  }
  if (safety.isError) {
    checks.push({
      name: 'New trades switched on',
      ok: false,
      note: 'The safety switch could not be checked. Treat new trades as paused.',
      hard: true,
    })
  } else if (safety.data) {
    checks.push({
      name: 'New trades switched on',
      ok: safety.data.new_entries_enabled,
      note: safety.data.new_entries_enabled ? undefined : safety.data.halt_reason ?? 'New trades are paused.',
      hard: true,
    })
  }
  const blocked = checks.filter((c) => !c.ok)
  const hardBlocked = blocked.filter((c) => c.hard)
  const softBlocked = blocked.filter((c) => !c.hard)
  const cannotConfirmSafety = safety.isError
  const paused = hardBlocked.length > 0

  return (
    <div className="tm-page tm-grid">
      {inputsLoading ? (
        <Card>
          <p className="tm-dim">Checking today's safety status…</p>
        </Card>
      ) : (
        <Card glow={paused ? true : softBlocked.length ? true : 'green'}>
          <div className="tm-between tm-wrap">
            <div className="tm-flex">
              <span
                className="tm-state-icon"
                style={
                  paused
                    ? { borderColor: 'var(--tm-red)', color: 'var(--tm-red)', boxShadow: '0 0 24px rgba(255,77,106,.5)' }
                    : softBlocked.length
                    ? { borderColor: 'var(--tm-amber)', color: 'var(--tm-amber)', boxShadow: '0 0 24px rgba(255,181,71,.5)' }
                    : undefined
                }
              >
                <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z" />
                </svg>
              </span>
              <div>
                <div
                  className="tm-state-word"
                  style={{
                    fontSize: '1.5rem',
                    color: paused ? 'var(--tm-red)' : softBlocked.length ? 'var(--tm-amber)' : undefined,
                    textShadow: 'none',
                  }}
                >
                  {cannotConfirmSafety
                    ? 'CAN\'T CONFIRM — the safety switch could not be checked. Treat new trades as paused.'
                    : paused
                    ? 'NEW TRADES PAUSED'
                    : softBlocked.length
                    ? 'TRADING ALLOWED — WITH LIMITS'
                    : 'ALL CLEAR'}
                </div>
                <div className="tm-dim" style={{ marginTop: 4 }}>
                  {paused
                    ? hardBlocked.map((b) => b.note ?? b.name).join('; ')
                    : softBlocked.length
                    ? `${softBlocked.length} check${softBlocked.length > 1 ? 's' : ''} need attention: ${softBlocked.map((b) => b.name).join('; ')}`
                    : 'Every safety check passed — new trades are allowed.'}
                </div>
              </div>
            </div>
          </div>
        </Card>
      )}

      <div className="tm-grid tm-cols-4">
        <Card>
          <div className="tm-score">
            <Ring
              value={Math.round(deployedPct)}
              size={76}
              stroke={7}
              color="blue"
              center={<span className="tm-ring-value" style={{ fontSize: 16 }}>{Math.round(deployedPct)}%</span>}
            />
            <div>
              <div className="tm-score-name">Capital deployed</div>
              <div className="tm-score-verdict">of today's ceiling</div>
            </div>
          </div>
        </Card>
        {equity.isLoading ? (
          <Card>
            <p className="tm-dim">Loading…</p>
          </Card>
        ) : equity.isError ? (
          <Card title="Drawdown">
            <p className="tm-dim">Could not load portfolio history. Try again shortly.</p>
          </Card>
        ) : ddPct != null ? (
          <Card>
            <div className="tm-score">
              <Ring
                value={Math.round(ddPct * 10) / 10}
                max={haltPct}
                size={76}
                stroke={7}
                color="red"
                center={<span className="tm-ring-value" style={{ fontSize: 16 }}>{ddPct.toFixed(1)}%</span>}
              />
              <div>
                <div className="tm-score-name">Drawdown (halt at {haltPct.toFixed(0)}%)</div>
                <div className={ddPct < haltPct ? 'tm-score-verdict tm-pos' : 'tm-score-verdict tm-warn'}>
                  {ddPct < haltPct ? 'Safe' : 'At the halt level'}
                </div>
              </div>
            </div>
          </Card>
        ) : (
          <NotConnected what="Drawdown" reason="No portfolio history yet." />
        )}
        <Card>
          <div className="tm-score">
            <Ring
              value={d.open_positions}
              max={Math.max(d.max_positions, d.open_positions)}
              size={76}
              stroke={7}
              color="violet"
              center={<span className="tm-ring-value" style={{ fontSize: 18 }}>{d.open_positions}/{d.max_positions}</span>}
            />
            <div>
              <div className="tm-score-name">Open positions</div>
              <div className="tm-score-verdict">
                {d.open_positions > d.max_positions
                  ? 'Over the limit'
                  : `${d.max_positions - d.open_positions} slot${d.max_positions - d.open_positions === 1 ? '' : 's'} free`}
              </div>
            </div>
          </div>
        </Card>
        <Card>
          <div className="tm-score">
            <Ring
              value={Math.round(cashPct)}
              size={76}
              stroke={7}
              color="green"
              center={<span className="tm-ring-value" style={{ fontSize: 18 }}>{Math.round(cashPct)}%</span>}
            />
            <div>
              <div className="tm-score-name">Cash available</div>
              <div className="tm-score-verdict">{d.cash >= d.cash_floor_inr ? 'Above the reserved floor' : 'Below the reserved floor'}</div>
            </div>
          </div>
        </Card>
      </div>

      <div className="tm-grid tm-cols-3">
        <Card className="tm-span-2" title="Risk Limits" sub="Each bar shows how close you are to a hard limit">
          <div className="tm-stack" style={{ gap: '0.9rem' }}>
            {[
              { name: 'Open positions', used: d.open_positions, limit: d.max_positions, unit: '', plain: 'Most trades held at once' },
              {
                name: 'Capital deployed',
                used: Math.round(deployedPct),
                limit: 100,
                unit: '%',
                plain: "How much of today's allowed capital is in stocks",
              },
              ...(d.sector_cap_pct != null && big
                ? [
                    {
                      name: `Biggest sector (${big.sector})`,
                      used: Math.round(big.pct_of_portfolio * 100),
                      limit: Math.round(d.sector_cap_pct * 100),
                      unit: '%',
                      plain: 'No sector should be over the cap',
                    },
                  ]
                : []),
              ...(ddPct != null
                ? [
                    {
                      name: 'Drawdown from peak',
                      used: Math.round(ddPct * 10) / 10,
                      limit: Math.round(haltPct),
                      unit: '%',
                      plain: 'Trading stops automatically at this level',
                    },
                  ]
                : []),
            ].map((l) => {
              // A limit of 0 would otherwise divide by zero and render an
              // "Infinity%" bar (M7).
              const pct = l.limit > 0 ? (l.used / l.limit) * 100 : 0
              const color = pct >= 100 ? '#ff4d6a' : pct >= 75 ? '#ffb547' : '#2ee68a'
              return (
                <div key={l.name}>
                  <div className="tm-between" style={{ marginBottom: 4 }}>
                    <span>
                      <span className="tm-strong">{l.name}</span>
                      <span className="tm-faint"> · {l.plain}</span>
                    </span>
                    <span className="tm-num" style={{ color, fontWeight: 600 }}>
                      {l.used}
                      {l.unit} / {l.limit}
                      {l.unit}
                    </span>
                  </div>
                  <Meter pct={pct} color={color} />
                </div>
              )
            })}
          </div>
        </Card>
        <Card title="Safety Checks" sub="Checked against your risk limits right now">
          {checks.map((c) => (
            <CheckItem key={c.name} tone={c.ok ? 'pos' : 'warn'}>
              {c.name}
              {c.note && <div className="tm-faint">{c.note}</div>}
            </CheckItem>
          ))}
        </Card>
      </div>

      <div className="tm-grid tm-cols-3">
        {equity.isLoading ? (
          <div className="tm-span-2">
            <Card title="Drawdown">
              <p className="tm-dim">Loading…</p>
            </Card>
          </div>
        ) : equity.isError ? (
          <div className="tm-span-2">
            <Card title="Drawdown">
              <p className="tm-dim">Could not load portfolio history. Try again shortly.</p>
            </Card>
          </div>
        ) : points.length > 1 ? (
          <Card className="tm-span-2" title="Drawdown" sub="How far the portfolio was below its best point, day by day">
            <GlowArea data={drawdownChartSeries(points)} color="#ff4d6a" height={180} axes domain={['dataMin', 0]} formatter={(v) => `${v.toFixed(1)}%`} />
          </Card>
        ) : (
          <div className="tm-span-2">
            <NotConnected what="Drawdown" reason="Not enough portfolio history yet to draw a chart." />
          </div>
        )}
        <Card title="What these limits do automatically">
          <CheckItem tone="neutral">Each trade risks about {(d.risk_per_trade_pct * 100).toFixed(1)}% of the account</CheckItem>
          <CheckItem tone="neutral">Drawdown hits {haltPct.toFixed(0)}% → stops all new trades</CheckItem>
          {d.sector_cap_pct != null && (
            <CheckItem tone="neutral">A sector over {(d.sector_cap_pct * 100).toFixed(0)}% → no more trades in it</CheckItem>
          )}
          <CheckItem tone="neutral">
            The market looks {d.plain_regime} → up to {(d.deployable_fraction * 100).toFixed(0)}% of the account can be in stocks
          </CheckItem>
        </Card>
      </div>

      <Card
        title="Ideas Turned Down Today"
        sub="The reason shown is the brain's own — a turn-down can come from stale data or a careful market, not only the risk check."
      >
        {brainStatus === 'off' && <BrainOff />}
        {brainStatus === 'loading' && <p className="tm-dim">Connecting to the brain…</p>}
        {brainStatus === 'error' && <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>}
        {brainStatus === 'no-run' && <p className="tm-dim">The brain has not run yet.</p>}
        {brainStatus === 'live' && latest.data && (
          <>
            {refusedDecisions(latest.data).length === 0 ? (
              <p className="tm-dim">Nothing was turned down in the latest run.</p>
            ) : (
              refusedDecisions(latest.data).map((dec) => (
                <CheckItem key={dec.id} tone="warn">
                  <span className="tm-strong">{dec.symbol}</span>: turned down — {dec.downgrade_reason}
                </CheckItem>
              ))
            )}
          </>
        )}
      </Card>
    </div>
  )
}
