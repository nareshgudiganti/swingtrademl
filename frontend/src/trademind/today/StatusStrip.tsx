// oa5: Today's status strip. Left: the market mode and banner from the brain's latest run (everyone; moved from
// Home's hero). Right: the owner's safety picture — kill switch, drawdown against the halt level, trading stage —
// each linking to the page where it is changed. Display only. The safety answers are owner-only on the server
// (/safety, /brain/stage), so they are not even asked for anyone else.

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import { formatDateTime } from '../../lib/format'
import { currentDrawdownPct } from '../live-system'
import { marketSituation, useLatestRun } from '../live'
import { TermIf, Term } from '../term'
import { BrainArt, Icon, Tag } from '../ui'
import { MARKET_LABEL, MARKET_PLAIN, MARKET_TONE } from '../vocab'
import { drawdownLine, killSwitchLine, stageLine, type SafetyLine } from './statusRules'

export function StatusStrip({ owner }: { owner: boolean }) {
  const latest = useLatestRun()
  const run = latest.data
  const situation = run ? marketSituation(run) : undefined
  const mode = run?.banner.mode

  return (
    <section className="tm-card tm-glow tm-hero tm-today-status" data-testid="status-strip" aria-label="Status">
      <div>
        <div className="tm-card-title" style={{ marginBottom: '0.9rem' }}>
          <Term k="market_mode">Market Mode</Term>
        </div>
        {!run ? (
          <p className="tm-dim">{latest.isLoading ? "Waiting for the brain's latest run…" : 'The brain has not run yet, so there is nothing to show here.'}</p>
        ) : (
          <>
            <p className="tm-dim" style={{ fontSize: '0.72rem', margin: '-0.6rem 0 0.9rem' }} data-feature="run-time">
              From the brain's run on {formatDateTime(run.started_at)}
            </p>
            <div className="tm-hero-state" data-feature="market-mode">
              <span
                className="tm-state-icon"
                style={
                  mode && MARKET_TONE[mode] !== 'green'
                    ? MARKET_TONE[mode] === 'red'
                      ? { borderColor: 'var(--tm-red)', color: 'var(--tm-red)', boxShadow: '0 0 24px rgba(255,77,106,.5)' }
                      : { borderColor: 'var(--tm-amber)', color: 'var(--tm-amber)', boxShadow: '0 0 24px rgba(255,181,71,.5)' }
                    : undefined
                }
              >
                {mode === 'NO_NEW_TRADES' ? <Icon.X /> : mode === 'DEFENSIVE' ? <Icon.Alert /> : <Icon.Check />}
              </span>
              <div>
                <div className="tm-state-word">{mode ? <TermIf k={mode}>{MARKET_LABEL[mode] ?? mode}</TermIf> : 'Unknown'}</div>
                {mode && <Tag tone={MARKET_TONE[mode] ?? 'blue'}>{MARKET_PLAIN[mode]}</Tag>}
              </div>
            </div>
            {run.banner.headline && (
              <p className="tm-dim" style={{ fontSize: '0.78rem', margin: '0.9rem 0 0', maxWidth: 420 }} data-feature="banner-headline">
                {run.banner.headline}
              </p>
            )}
            {situation && situation.label !== 'unlabelled' && (
              <p className="tm-note" style={{ marginTop: '0.6rem' }} data-feature="market-situation">
                Situation: {situation.label}
                {situation.is_unknown ? ' — never seen before' : ''}
                {situation.evidence[0] ? ` — ${situation.evidence[0]}` : ''}
              </p>
            )}
          </>
        )}
      </div>

      {owner ? (
        <Safety />
      ) : (
        <div className="tm-brain">
          <BrainArt />
          <div className="tm-brain-title">TradeMind Brain</div>
          <p className="tm-dim" style={{ fontSize: '0.74rem', textAlign: 'center', margin: '0.4rem 0 0' }}>
            Practice mode: everything here is paper trading.
          </p>
        </div>
      )}
    </section>
  )
}

function Safety() {
  const safety = useQuery({ queryKey: ['safetyState'], queryFn: api.safetyState })
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage, retry: false })
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits })
  const equity = useQuery({ queryKey: ['equityCurve', 400], queryFn: () => api.equityCurve(400) })

  const ddPct = equity.data ? currentDrawdownPct(equity.data) : null
  const haltPct = limits.data?.max_drawdown_pct != null ? limits.data.max_drawdown_pct * 100 : null
  const lines: SafetyLine[] = [
    killSwitchLine(safety.data, safety.isError && safety.data === undefined),
    drawdownLine(ddPct, haltPct, (equity.isError && !equity.data) || (limits.isError && !limits.data)),
    stageLine(stage.data, stage.isError && stage.data === undefined),
  ]

  return (
    <div className="tm-today-safety" aria-label="Safety">
      <div className="tm-card-title" style={{ marginBottom: '0.6rem' }}>
        Safety
      </div>
      {lines.map((l) => (
        <Link key={l.id} to={l.to} className="tm-today-safety-row" data-feature={l.id} data-tone={l.tone}>
          <span className="tm-dim">{l.label}</span>
          <Tag tone={l.tone}>{l.value}</Tag>
          {l.note && <small className="tm-dim">{l.note}</small>}
        </Link>
      ))}
    </div>
  )
}
