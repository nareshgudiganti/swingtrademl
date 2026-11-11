// Portfolio > Reports: "I picked WATCH (or Buy) with a score of 70-80 — how many stocks is that, how many days have
// passed, how many are left, and what happened?" Read-only: it only reads the brain's stored ideas. By default it
// lists only the stocks we hold or have sold. While the blind trial is sealed the server sends no returns or
// results, only days and scores, and this card says so.

import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { IdeaReportRow } from '../../api/types'
import { Card, Icon, Tag, toneClass } from '../ui'
import StockLink from '../StockLink'
import { PageState } from '../PageState'
import { pickState } from '../stateRules'

const WORD_NAME: Record<string, string> = { TRADE: 'Buy', WATCH: 'Watch', WAIT: 'Wait', AVOID: 'Avoid' }
const WORD_TONE: Record<string, 'green' | 'amber' | 'red' | 'blue'> = {
  TRADE: 'green',
  WATCH: 'green',
  WAIT: 'amber',
  AVOID: 'red',
}
const MOOD_NAME: Record<string, string> = {
  NORMAL: 'Normal market',
  DEFENSIVE: 'Cautious market',
  NO_NEW_TRADES: 'No-new-trades market',
}
const OUTCOME_NAME: Record<string, string> = {
  target: 'Hit +8% first',
  stop: 'Hit −4% first',
  timeout: 'Ended without either',
  open: 'Still running',
}
const DEFAULTS = { scope: 'mine' as 'mine' | 'all', word: 'WATCH', band: '', horizon: '', mood: '', outcome: '', currentOnly: false }

/** One compact dropdown; '' means "Any" (no filter). */
function Pick({
  label,
  options,
  value,
  onChange,
  name,
  disabled,
  anyText = 'Any',
}: {
  label: string
  options: string[]
  value: string
  onChange: (v: string) => void
  name?: (v: string) => string
  disabled?: boolean
  anyText?: string
}) {
  return (
    <label className="ir-pick">
      <span className="tm-stat-label">{label}</span>
      <select className="tm-select" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        <option value="">{anyText}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {name ? name(o) : o}
          </option>
        ))}
      </select>
    </label>
  )
}

const day = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const pct = (n: number | null) => (n === null ? '—' : `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(1)}%`)

function ResultCell({ r, sealed }: { r: IdeaReportRow; sealed: boolean }) {
  if (sealed) return <span className="tm-dim">Sealed</span>
  if (r.outcome === null)
    return r.status === 'due' ? <Tag tone="amber">Waiting for result</Tag> : <Tag tone="green">Still running</Tag>
  return (
    <span className={toneClass(r.return_pct ?? 0)}>
      {pct(r.return_pct)} <span className="tm-dim">· {OUTCOME_NAME[r.outcome]}</span>
    </span>
  )
}

function Stat({ icon, label, value, note }: { icon: ReactNode; label: string; value: string; note?: string }) {
  return (
    <div className="ir-stat">
      <span className="ir-stat-icon" aria-hidden="true">
        {icon}
      </span>
      <div>
        <div className="tm-stat-value">{value}</div>
        <div className="tm-stat-label">{label}</div>
        {note && <div className="tm-dim">{note}</div>}
      </div>
    </div>
  )
}

export default function IdeaReports() {
  const [scope, setScope] = useState(DEFAULTS.scope) // only stocks we hold or have sold, unless asked
  const [word, setWord] = useState(DEFAULTS.word)
  const [band, setBand] = useState(DEFAULTS.band)
  const [horizon, setHorizon] = useState(DEFAULTS.horizon)
  const [mood, setMood] = useState(DEFAULTS.mood)
  const [outcome, setOutcome] = useState(DEFAULTS.outcome)
  const [currentOnly, setCurrentOnly] = useState(DEFAULTS.currentOnly)
  const one = (v: string) => (v ? [v] : [])
  const reset = () => {
    setScope(DEFAULTS.scope)
    setWord(DEFAULTS.word)
    setBand(DEFAULTS.band)
    setHorizon(DEFAULTS.horizon)
    setMood(DEFAULTS.mood)
    setOutcome(DEFAULTS.outcome)
    setCurrentOnly(DEFAULTS.currentOnly)
  }

  const q = useQuery({
    queryKey: ['ideaReport', scope, word, band, horizon, mood, outcome, currentOnly],
    queryFn: () =>
      api.ideaReport({
        word: one(word),
        band: one(band),
        horizon: one(horizon).map(Number),
        regime: one(mood),
        outcome: one(outcome),
        current_only: currentOnly,
        mine_only: scope === 'mine',
      }),
    retry: false,
    placeholderData: (prev) => prev,
  })

  // Not the owner, or the brain is off: this report does not exist for them, so show nothing.
  const state = pickState(q)
  if (state === 'forbidden' || state === 'not-found') return null

  const d = q.data
  const sealed = !!d?.seal.active
  const wordText = word ? (WORD_NAME[word] ?? word) : 'this word'
  const res = d?.summary.results
  const resTotal = res ? res.target + res.stop + res.timeout : 0
  const share = (n: number) => (resTotal ? Math.round((n / resTotal) * 100) : 0)
  return (
    <Card
      title="Idea reports"
      sub="Only the stocks we hold or have sold, unless you switch to every idea. See how many days have passed and what happened."
    >
      {d && (
        <>
          <div className="ir-filters" data-testid="report-filters">
            <div className="ir-pick ir-decision">
              <span className="tm-stat-label">Decision</span>
              <div className="ir-seg" role="group" aria-label="Decision">
                <button type="button" aria-pressed={word === ''} onClick={() => setWord('')}>
                  All
                </button>
                {d.options.words.map((w) => (
                  <button key={w} type="button" aria-pressed={word === w} onClick={() => setWord(w)}>
                    {WORD_NAME[w] ?? w}
                  </button>
                ))}
              </div>
            </div>
            <Pick label="Score" options={d.options.bands} value={band} onChange={setBand} anyText="All scores" />
            <Pick
              label="Horizon"
              options={d.options.horizons.map(String)}
              value={horizon}
              onChange={setHorizon}
              name={(h) => `${h} days`}
              anyText="All horizons"
            />
            <Pick
              label="Market mood"
              options={d.options.regimes}
              value={mood}
              onChange={setMood}
              name={(m) => MOOD_NAME[m] ?? m}
              anyText="All moods"
            />
            <Pick
              label="Outcome"
              options={d.options.outcomes}
              value={outcome}
              onChange={setOutcome}
              name={(o) => OUTCOME_NAME[o] ?? o}
              disabled={sealed}
              anyText="All outcomes"
            />
            <div className="ir-toggles">
              <label className="ir-toggle">
                <input type="checkbox" role="switch" checked={currentOnly} onChange={(e) => setCurrentOnly(e.target.checked)} />
                <span>Still rated {wordText} today</span>
              </label>
              <label className="ir-toggle">
                <input
                  type="checkbox"
                  role="switch"
                  checked={scope === 'mine'}
                  onChange={(e) => setScope(e.target.checked ? 'mine' : 'all')}
                />
                <span>Only stocks we hold or sold</span>
              </label>
            </div>
            <button type="button" className="ir-reset" onClick={reset}>
              Reset filters
            </button>
          </div>
          {sealed && (
            <p className="tm-dim" data-testid="report-sealed">
              Results are hidden while the test is running (from {d.seal.from ? day(d.seal.from) : 'its start'}), so the
              test stays fair. You can see how many stocks, the score, and the days done and left. “What happened” and
              the +8% / −4% results unlock when the test is reviewed.
            </p>
          )}
          <div className="ir-stats" data-testid="report-summary">
            <Stat
              icon={<Icon.Layers size={22} />}
              label="Tracked ideas"
              value={String(d.summary.ideas)}
              note={`${d.summary.still_this_word} still have this word`}
            />
            <Stat icon={<Icon.Pulse size={22} />} label="Still running" value={String(d.summary.tracking)} />
            <Stat
              icon={<Icon.Check size={22} />}
              label="Finished"
              value={String(d.summary.finished + d.summary.due)}
              note={d.summary.due ? `${d.summary.due} waiting for result` : undefined}
            />
            <Stat
              icon={<Icon.Chart size={22} />}
              label={sealed ? 'Results' : 'Average return'}
              value={sealed ? 'Hidden' : res?.avg_return_pct == null ? '—' : pct(res.avg_return_pct)}
              note={sealed ? 'until the test is reviewed' : 'for finished ideas'}
            />
          </div>
          {!sealed && res && resTotal > 0 && (
            <div className="ir-outcomes" data-testid="report-outcomes">
              <h4 className="ir-h">Finished outcomes</h4>
              <div
                className="ir-bar"
                role="img"
                aria-label={`Hit +8% first ${share(res.target)}%, hit −4% first ${share(res.stop)}%, neither ${share(res.timeout)}%`}
              >
                {res.target > 0 && (
                  <span className="ir-bar-win" style={{ flexGrow: res.target }}>
                    {share(res.target)}%
                  </span>
                )}
                {res.stop > 0 && (
                  <span className="ir-bar-loss" style={{ flexGrow: res.stop }}>
                    {share(res.stop)}%
                  </span>
                )}
                {res.timeout > 0 && (
                  <span className="ir-bar-flat" style={{ flexGrow: res.timeout }}>
                    {share(res.timeout)}%
                  </span>
                )}
              </div>
              <div className="ir-legend">
                <span>
                  <i className="ir-bar-win" /> Hit +8% first · {res.target}
                </span>
                <span>
                  <i className="ir-bar-loss" /> Hit −4% first · {res.stop}
                </span>
                <span>
                  <i className="ir-bar-flat" /> Neither · {res.timeout}
                </span>
              </div>
            </div>
          )}
        </>
      )}
      {!d && state !== 'ready' && state !== 'empty' && (
        <PageState kind={state} what="the idea report" error={q.error} onRetry={q.refetch} />
      )}
      {d && d.rows.length === 0 && (
        <PageState kind="empty" reason="No stocks match these choices in the last 60 days. Try fewer filters." />
      )}
      {d && d.rows.length > 0 && (
        <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Idea report, scroll sideways to see more">
          <table className="tm-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th>Decision</th>
                <th>First seen</th>
                <th>Sessions left</th>
                <th>Score then → now</th>
                <th>Market mood</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={`${r.symbol}-${r.word}-${r.entry_day}`}>
                  <td>
                    <StockLink symbol={r.symbol} />
                  </td>
                  <td>
                    <Tag tone={WORD_TONE[r.word] ?? 'blue'}>{WORD_NAME[r.word] ?? r.word}</Tag>
                    {!r.still_this_word && <div className="tm-dim">now {WORD_NAME[r.latest_word] ?? r.latest_word}</div>}
                  </td>
                  <td>{day(r.entry_day)}</td>
                  <td className="tm-num">
                    {r.days_left} of {r.horizon_days}
                  </td>
                  <td className="tm-num">
                    {r.entry_score ?? '—'} → {r.latest_score ?? '—'}
                  </td>
                  <td>{r.regime ? (MOOD_NAME[r.regime] ?? r.regime) : '—'}</td>
                  <td>
                    <ResultCell r={r} sealed={r.sealed} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
