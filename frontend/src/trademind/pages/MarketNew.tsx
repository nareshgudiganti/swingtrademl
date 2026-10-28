// The new look's Market page: the market mode as one big answer, the three-step ladder, the facts the data gives,
// what it means for you, and sector strength. Display only: reads the brain's latest run, the NIFTY regime and the
// account's limits; changes nothing. "What would bring it back to Normal" is left out: no stored data states it,
// and this page never guesses.

import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import { usePlan } from '../../lib/plan'
import { formatDateTime } from '../../lib/format'
import { marketSituation, useEpisodes, useLatestRun } from '../live'
import { QueryNotice } from '../PageState'
import { BrainGate, inr } from '../ui'
import { MARKET_LABEL, MARKET_PLAIN, MARKET_TONE } from '../vocab'
import { LADDER, meansForYou, pctText, sectorBar, sectorRows, shortDate } from '../wave3Rules'
import '../newlook-w3.css'

const TREND: Record<string, string> = {
  bullish: 'Above its own trend — a rising market',
  bearish: 'Below its own trend — a falling market',
}
const SWINGS: Record<string, string> = { elevated: 'High', normal: 'Normal', low: 'Low' }
const SIZE: Record<string, string> = { NORMAL: 'Full', DEFENSIVE: 'Half', NO_NEW_TRADES: 'None' }
const ROTATION: Record<string, string> = {
  leading: 'Leading',
  improving: 'Improving',
  weakening: 'Weakening',
  lagging: 'Lagging',
  unknown: 'Too little history',
}

export default function MarketNew() {
  return (
    <div className="tm-page tmw3" data-page="market-new">
      <div className="tmw3-head">
        <h2 className="tmw3-h1">Market</h2>
        <p className="tm-dim">How the whole market looks tonight, and what that means for your money.</p>
      </div>
      <BrainGate inline>
        <MarketBody />
      </BrainGate>
    </div>
  )
}

function MarketBody() {
  const run = useLatestRun().data!
  const regime = useQuery({ queryKey: ['marketRegime'], queryFn: api.marketRegime })
  // The account's invested ceiling (version 1's limits). Refused for some plans: then the line is left out.
  const { canManage } = usePlan()
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits, retry: false, enabled: canManage })
  const mode = run.banner.mode
  const tone = (mode && MARKET_TONE[mode]) || 'blue'
  const situation = marketSituation(run)
  const investedPct = limits.data ? limits.data.deployable_fraction * 100 : null
  const r = regime.data

  return (
    <>
      <section className="tmn-card tmw3-mode" data-tone={tone} aria-label="Market mode" data-testid="market-mode">
        <div className="tmw3-mode-word">{mode ? MARKET_LABEL[mode] ?? mode : 'Unknown'}</div>
        <p>{(mode && MARKET_PLAIN[mode]) ?? 'The brain did not say what mode the market is in.'}</p>
        {run.banner.headline && <p className="tm-dim">{run.banner.headline}</p>}
        <div className="tmw3-ladder" aria-label="The three market modes">
          {LADDER.map((rung) => (
            <div key={rung.mode} className={`tmw3-rung ${rung.mode === mode ? 'on' : ''}`} data-tone={rung.tone} aria-current={rung.mode === mode ? 'step' : undefined}>
              <b>{`${rung.label}${rung.mode === mode ? ' · now' : ''}`}</b>
              <span className="tmn-small tm-dim">{rung.line}</span>
            </div>
          ))}
        </div>
        <p className="tmn-small tm-faint">From the brain&apos;s run on {formatDateTime(run.started_at)}</p>
      </section>

      <div className="tmw3-facts" data-testid="market-facts">
        <div className="tmn-card">
          <QueryNotice q={regime} what="the NIFTY level" />
          {r && (
            <>
              <div className="tmw3-big">{r.nifty_close != null ? `${inr(r.nifty_close, 0)}` : '—'}</div>
              <div className="tmn-small tm-dim">{`NIFTY 50${r.as_of ? `, close of ${shortDate(r.as_of)}` : ''}`}</div>
              {TREND[r.regime] && <div className="tmn-small">{TREND[r.regime]}</div>}
            </>
          )}
        </div>
        <div className="tmn-card">
          {r && SWINGS[r.volatility_level] ? (
            <>
              <div className="tmw3-big">{SWINGS[r.volatility_level]}</div>
              <div className="tmn-small tm-dim">Daily swings (volatility)</div>
            </>
          ) : (
            <>
              <div className="tmw3-big">—</div>
              <div className="tmn-small tm-dim">Daily swings: not known</div>
            </>
          )}
        </div>
        <div className="tmn-card">
          <div className="tmw3-big">{mode ? SIZE[mode] ?? '—' : '—'}</div>
          <div className="tmn-small tm-dim">Size of each new buy</div>
        </div>
      </div>

      <div className="tmn-row-2">
        <section className="tmn-card" aria-label="What this means for you" data-testid="means-for-you">
          <div className="tmn-card-head">
            <span className="tmn-card-title">What this means for you</span>
          </div>
          <ul className="tmw3-checks">
            {meansForYou(mode, investedPct).map((line) => (
              <li key={line}>
                <span className="tmw3-tick" aria-hidden="true">
                  ✓
                </span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
          {situation && situation.label !== 'unlabelled' && (
            <p className="tmn-small tm-dim">
              The brain names today&apos;s market: {situation.label}
              {situation.is_unknown ? ' (never seen before)' : ''}.
            </p>
          )}
        </section>
        <Sectors />
      </div>

      <History />
    </>
  )
}

function Sectors() {
  const run = useLatestRun().data!
  const rows = sectorRows(run.sectors ?? [])
  const maxAbs = Math.max(0, ...rows.map((r) => Math.abs(r.pct ?? 0)))
  return (
    <section className="tmn-card" aria-label="Sector strength" data-testid="sectors">
      <div className="tmn-card-head">
        <span className="tmn-card-title">Sector strength</span>
        <span className="tmn-small tm-dim">Change over 20 trading days</span>
      </div>
      {rows.length === 0 ? (
        <p className="tm-dim">No sector figures in this run.</p>
      ) : (
        <>
          <div className="tmw3-sectors">
            {rows.map((s) => {
              const bar = s.pct == null ? null : sectorBar(s.pct, maxAbs)
              return (
                <div key={s.key} className="tmw3-sector" title={ROTATION[s.rotation] ?? s.rotation}>
                  <span className="tmw3-sector-name">{s.name}</span>
                  <span className="tmw3-track" aria-hidden="true">
                    {bar && <span className={s.pct! >= 0 ? 'up' : 'down'} style={{ left: `${bar.left}%`, width: `${bar.width}%` }} />}
                  </span>
                  <b className={s.pct == null ? 'tm-dim' : s.pct >= 0 ? 'tm-pos' : 'tm-neg'}>{s.pct == null ? '—' : pctText(s.pct)}</b>
                </div>
              )
            })}
          </div>
          <p className="tmn-small tm-dim">The centre line is no change. Green grew, red fell.</p>
        </>
      )}
    </section>
  )
}

/** The stretches the market went through, as the brain names them (same data as the classic page). */
function History() {
  const episodes = useEpisodes()
  const list = (episodes.data ?? []).slice(0, 6)
  return (
    <section className="tmn-card" aria-label="Market history">
      <div className="tmn-card-head">
        <span className="tmn-card-title">Recent market stretches</span>
        <span className="tmn-small tm-dim">As the brain names them</span>
      </div>
      <QueryNotice q={episodes} what="market history" />
      {episodes.data && list.length === 0 && <p className="tm-dim">No history recorded yet.</p>}
      {list.length > 0 && (
        <ul className="tmw3-list">
          {list.map((e) => (
            <li key={e.start_day}>
              <span className="tm-strong">{e.label}</span>
              <span className="tm-dim tmn-small">
                {e.start_day} to {e.end_day ?? 'still going'}
              </span>
              <b className={e.nifty_change == null ? 'tm-dim' : e.nifty_change >= 0 ? 'tm-pos' : 'tm-neg'}>
                {e.nifty_change == null ? '—' : `NIFTY ${pctText(e.nifty_change * 100)}`}
              </b>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
