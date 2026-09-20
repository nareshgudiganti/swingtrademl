import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatPercent } from '../lib/format'

/** The ladder rung names, so the account knows where it stands without the
 * user having to read a rupee figure and work it out. */
function rungLabel(rungValue: number): string {
  if (rungValue <= 10_000) return 'Proving the plumbing'
  if (rungValue <= 100_000) return 'First real evidence'
  if (rungValue <= 1_000_000) return 'The design centre'
  if (rungValue <= 2_500_000) return 'Spreading out'
  if (rungValue <= 5_000_000) return 'Capacity pressure'
  return 'Where the strategy caps out'
}

export default function Capital() {
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits })
  const events = useQuery({ queryKey: ['riskEvents'], queryFn: () => api.riskEvents(100) })
  const d = limits.data

  // Today only: the point of this panel is what the ceilings cost *now*, not
  // a history. The full log lives on Safety.
  const today = new Date().toDateString()
  const blockedToday = (events.data ?? []).filter(
    (e) => new Date(e.ts).toDateString() === today,
  )

  return (
    <>
      <div className="page-head">
        <h1>Capital</h1>
      </div>

      {limits.isLoading && <Loading />}
      {limits.isError && <ErrorBox error={limits.error as Error} />}

      {d && (
        <>
          <div className="card" style={{ marginBottom: '1.25rem' }}>
            <h2>Where your money is</h2>
            <div className="grid" style={{ marginTop: '0.8rem', marginBottom: '1rem' }}>
              <div>
                <div className="stat-label">Total</div>
                <div className="stat-value">{formatCurrency(d.portfolio_value)}</div>
              </div>
              <div>
                <div className="stat-label">At work</div>
                <div className="stat-value">{formatCurrency(d.invested_inr)}</div>
                <div className="stat-sub">
                  {/* Holding more than the rung allows is a real state, not an
                      error: positions opened at a larger account size are never
                      force-sold when the ladder tightens. Say so rather than
                      printing "13 of 5", which reads as a bug. */}
                  {d.open_positions > d.max_positions ? (
                    <>
                      {d.open_positions} stocks &middot;{' '}
                      <span className="warnc">over the limit of {d.max_positions}</span>
                    </>
                  ) : (
                    `${d.open_positions} of ${d.max_positions} stocks`
                  )}
                </div>
              </div>
              <div>
                <div className="stat-label">In cash</div>
                <div className="stat-value">{formatCurrency(d.cash)}</div>
                <div className="stat-sub">
                  {formatCurrency(d.cash_floor_inr)} of it is reserved
                </div>
              </div>
              <div>
                <div className="stat-label">Room left today</div>
                <div className="stat-value">{formatCurrency(d.room_inr)}</div>
              </div>
            </div>

            {d.portfolio_value > 0 && (
              <>
                <div className="bar-track">
                  <div
                    className="bar-fill-invested"
                    style={{ width: `${Math.min((d.invested_inr / d.portfolio_value) * 100, 100)}%` }}
                  />
                  <div
                    className="bar-fill-room"
                    style={{
                      width: `${Math.max(
                        Math.min(
                          ((d.deployable_ceiling_inr - d.invested_inr) / d.portfolio_value) * 100,
                          100,
                        ),
                        0,
                      )}%`,
                    }}
                  />
                </div>
                <div className="between" style={{ marginTop: '0.5rem' }}>
                  <span className="stat-sub">
                    Invested {formatPercent(d.invested_inr / d.portfolio_value, 0)} · today&rsquo;s
                    ceiling {formatPercent(d.deployable_fraction, 0)}
                  </span>
                </div>
              </>
            )}
          </div>

          <div className="card" style={{ marginBottom: '1.25rem' }}>
            <h2>
              Why {formatPercent(d.deployable_fraction, 0)} and not more
            </h2>
            <p className="stat-sub" style={{ marginTop: '0.3rem' }}>
              The market looks <strong>{d.plain_regime}</strong>, so the bot is allowed to have{' '}
              {formatPercent(d.deployable_fraction, 0)} of the account in stocks right now — about{' '}
              {formatCurrency(d.deployable_ceiling_inr)}. Cash is a position, not what is left over.
            </p>
            <div className="grid" style={{ marginTop: '0.9rem' }}>
              <div>
                <div className="stat-label">Most in one stock</div>
                <div className="stat-value">{formatPercent(d.max_position_pct, 0)}</div>
              </div>
              <div>
                <div className="stat-label">Most in one sector</div>
                <div className="stat-value">
                  {d.sector_cap_pct != null ? formatPercent(d.sector_cap_pct, 0) : 'One each'}
                </div>
              </div>
              <div>
                <div className="stat-label">Risk per trade</div>
                <div className="stat-value">{formatPercent(d.risk_per_trade_pct, 1)}</div>
              </div>
              <div>
                <div className="stat-label">Halt if down</div>
                <div className="stat-value">{formatPercent(d.max_drawdown_pct, 0)}</div>
              </div>
            </div>
            <div className="note" style={{ marginTop: '1rem' }}>
              These limits are not fixed — they move with the size of the account. Yours currently
              sits at the <strong>{formatCurrency(d.rung_value)}</strong> rung,{' '}
              <em>{rungLabel(d.rung_value)}</em>. Smallest position worth taking:{' '}
              {formatCurrency(d.min_position_inr)}.
            </div>
          </div>

          <div className="card" style={{ marginBottom: '1.25rem' }}>
            <h2>Blocked today</h2>
            <p className="stat-sub" style={{ marginTop: '0.2rem' }}>
              {/* The limits above are abstract until you see what they cost.
                  Today's rejections are the same numbers, spent. */}
              Buys the model wanted that these limits turned away. Not errors — this is what the
              ceilings above actually did with your money today.
            </p>
            {blockedToday.length === 0 ? (
              <p className="stat-sub" style={{ marginTop: '0.6rem' }}>
                Nothing was blocked today.
              </p>
            ) : (
              <div style={{ marginTop: '0.8rem' }}>
                {blockedToday.slice(0, 8).map((e) => (
                  <div key={e.id} className="between" style={{ padding: '0.55rem 0' }}>
                    <div>
                      <strong>{e.symbol ?? 'A buy'}</strong>{' '}
                      <span className="muted">— {e.reason}</span>
                    </div>
                    <span className="badge badge-warn">{e.rule.replace(/_/g, ' ').toLowerCase()}</span>
                  </div>
                ))}
                {blockedToday.length > 8 && (
                  <div className="stat-sub" style={{ marginTop: '0.5rem' }}>
                    and {blockedToday.length - 8} more — see Safety for the full log.
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="card">
            <h2>Spread across sectors</h2>
            {d.sectors.length === 0 ? (
              <p className="stat-sub" style={{ marginTop: '0.3rem' }}>
                Nothing held yet, so there is nothing to spread.
              </p>
            ) : (
              <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Sector</th>
                      <th className="num">Held</th>
                      <th className="num">Share of account</th>
                      <th>Against the limit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.sectors.map((s) => {
                      const cap = d.sector_cap_pct
                      const atCap = cap != null && s.pct_of_portfolio >= cap
                      return (
                        <tr key={s.sector}>
                          <td>{s.sector}</td>
                          <td className="num">{formatCurrency(s.value_inr)}</td>
                          <td className="num">{formatPercent(s.pct_of_portfolio, 1)}</td>
                          <td>
                            {cap == null ? (
                              <span className="muted">One position per sector</span>
                            ) : (
                              <span className={`badge ${atCap ? 'badge-warn' : 'badge-on'}`}>
                                {atCap ? 'Full' : `Room to ${formatPercent(cap, 0)}`}
                              </span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  )
}
