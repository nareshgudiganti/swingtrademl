// The new look's Evidence page ("Is the brain any good?"): the sealed 15-day trial's progress, counts from the
// brain's latest run, the road to real money and a LOCKED daily scorecard. Display only, changes nothing.
//
// The trial is sealed until its review (7 Nov 2026): this page shows COUNTS ONLY — never the brain trial's profit,
// win rate or a comparison. The trading stage is owner-only on the server, so everyone else sees the three stages
// without the live count. The classic Learn page (learning report, proposals, glossary) stays one tap away.

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import { useLatestRun, useMarketSession } from '../live'
import { istToday } from '../pricesAge'
import {
  evidenceCounts,
  RESULTS_OPEN_TEXT,
  scorecardLockText,
  SEALED_RESULTS_TEXT,
  SEALED_RESULTS_TITLE,
  STAGES,
  TRIAL_START_TEXT,
  trialProgress,
} from '../wave3Rules'
import Learn from './Learn'
import '../newlook-w3.css'

export default function EvidenceNew({ owner = false }: { owner?: boolean }) {
  const market = useMarketSession()
  const today = market.data?.today ?? istToday(new Date())
  // Count up to the last finished trading day (the market's own calendar), else today.
  const asOf = market.data?.last_closed_trading_day ?? today
  const progress = trialProgress(asOf)

  return (
    <div className="tm-page tmw3" data-page="evidence-new">
      <div className="tmw3-head">
        <h2 className="tmw3-h1">
          Is the brain any good? <span className="tmw3-pill tmw3-pill-violet">Experimental</span>
        </h2>
        <p className="tm-dim">
          A sealed 15-day test. Nobody sees the results until it ends, so they can&apos;t be tweaked along the way.
        </p>
      </div>

      <section className="tmn-card" aria-label="Trial progress" data-testid="trial-progress">
        <div className="tmn-card-head">
          <span className="tmn-card-title">Trial progress</span>
          <b>{progress.day > 0 && !progress.finished ? `Day ${progress.day} of ${progress.of}` : progress.finished ? 'All days done' : 'Not started'}</b>
        </div>
        <div className="tmn-bar" aria-label={`${progress.pct}% of the trial's trading days done`}>
          <span style={{ width: `${progress.pct}%` }} />
        </div>
        <div className="tmw3-between tmn-small tm-dim">
          <span>Started {TRIAL_START_TEXT}</span>
          <span>Results open on {RESULTS_OPEN_TEXT}</span>
        </div>
        <p className="tmn-small tm-dim">
          {`${progress.line}.`} Counted in trading days: weekends and market holidays (20 Oct, 10 Nov) are skipped.
        </p>
        {owner && <OwnerSessions />}
      </section>

      <Counts />

      <div className="tmn-row-2">
        <section className="tmn-card tmw3-sealed" aria-label="Results sealed" data-testid="sealed-card">
          <span className="tmw3-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="4" y="10" width="16" height="10" rx="2" />
              <path d="M8 10V7a4 4 0 0 1 8 0v3" />
            </svg>
          </span>
          <div>
            <b>{SEALED_RESULTS_TITLE}</b>
            <p className="tm-dim">{SEALED_RESULTS_TEXT}</p>
          </div>
        </section>
        <RoadToRealMoney owner={owner} />
      </div>

      <section className="tmn-card tmw3-locked" aria-label="Daily scorecard" data-testid="scorecard">
        <div className="tmn-card-head">
          <span className="tmn-card-title">
            Daily scorecard <span className="tmn-small tm-dim">· {scorecardLockText(today)}</span>
          </span>
          <span className="tmw3-pill">Locked</span>
        </div>
        <div className="tmw3-score-grid" aria-hidden="true">
          <div>
            <div className="tmw3-big">—</div>
            <div className="tmn-small tm-dim">Brain&apos;s picks compared with buying every stock</div>
          </div>
          <div>
            <div className="tmw3-big">—</div>
            <div className="tmn-small tm-dim">Ideas that made money</div>
          </div>
          <div>
            <div className="tmw3-big">—</div>
            <div className="tmn-small tm-dim">Average gain and average loss</div>
          </div>
          <div>
            <div className="tmw3-big">—</div>
            <div className="tmn-small tm-dim">Open ideas today</div>
          </div>
        </div>
        <p className="tmn-small tm-dim">
          Once it opens: updated every evening from real market prices. Paper and real money are always shown
          separately, and every number says what it is compared with.
        </p>
      </section>

      <details className="tmn-more">
        <summary>More detail: the learning report, suggested changes and the word list</summary>
        <Learn />
      </details>
      {owner && (
        <p className="tmn-small">
          <Link className="tm-link" to="/trademind/observatory">
            Open the Observatory (owner only) →
          </Link>
        </p>
      )}
    </div>
  )
}

/** Owner only: how many nightly brain runs the trial has actually recorded (the stage endpoint's own count). */
function OwnerSessions() {
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage, retry: false })
  const sessions = stage.data?.trial?.sessions
  if (sessions == null) return null
  return (
    <p className="tmn-small tm-dim" data-testid="owner-sessions">
      {`Owner: ${sessions} nightly brain ${sessions === 1 ? 'run' : 'runs'} recorded for the trial so far.`}
    </p>
  )
}

/** Counts from the brain's latest run. Real-money trades are 0 only when the server says it is in paper mode. */
function Counts() {
  const latest = useLatestRun()
  const status = useQuery({ queryKey: ['status'], queryFn: api.status, retry: false })
  const c = latest.data ? evidenceCounts(latest.data) : null
  const real = status.data ? (status.data.trading_mode === 'paper' && !status.data.live_trading_enabled ? '0' : '—') : '—'
  const tiles: { n: string; label: string; tone: string }[] = [
    { n: c ? String(c.checked) : '—', label: 'Stocks checked tonight', tone: 'blue' },
    { n: c ? String(c.passedModel) : '—', label: 'Passed the model check', tone: 'green' },
    { n: c ? String(c.stoppedByRoom) : '—', label: 'Stopped by account room', tone: 'amber' },
    { n: real, label: 'Real-money trades', tone: 'grey' },
  ]
  return (
    <div className="tmw3-counts" data-testid="evidence-counts">
      {tiles.map((t) => (
        <div key={t.label} className="tmn-card tmw3-count" data-tone={t.tone}>
          <span className="tmw3-big">{t.n}</span>
          <span className="tmn-small tm-dim">{t.label}</span>
        </div>
      ))}
      <p className="tmn-small tm-faint tmw3-span">
        Counts only, from the brain&apos;s latest nightly run. &quot;Passed the model check&quot; means the model liked
        the stock enough to reach the safety check.
      </p>
    </div>
  )
}

function RoadToRealMoney({ owner }: { owner: boolean }) {
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage, enabled: owner, retry: false })
  const s = owner ? stage.data : undefined
  return (
    <section className="tmn-card" aria-label="Road to real money" data-testid="road-to-real">
      <div className="tmn-card-head">
        <span className="tmn-card-title">Road to real money</span>
        {s && (
          <span className="tmn-small tm-dim" data-testid="finished-count">
            {`${s.finished} of ${s.needed} ideas finished`}
          </span>
        )}
      </div>
      <ol className="tmw3-stages">
        {STAGES.map((st, i) => (
          <li key={st.id} className={s?.stage === st.id ? 'on' : ''} aria-current={s?.stage === st.id ? 'step' : undefined} title={st.plain}>
            {`${i + 1} · ${st.label}`}
          </li>
        ))}
      </ol>
      <p className="tmn-small tm-dim">
        After 30 finished practice ideas the owner can choose to move to stage 2. Real money is always the
        owner&apos;s decision.
      </p>
    </section>
  )
}
