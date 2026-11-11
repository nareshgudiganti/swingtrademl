// Portfolio > Reports: "I picked WATCH (or Buy) with a score of 70-80 — how many stocks is that, how many days have
// passed, how many are left, and what happened?" Read-only: it only reads the brain's stored ideas. While the blind
// trial is sealed the server sends no returns or results, only days and scores, and this card says so.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { IdeaReportRow } from '../../api/types'
import { Card, toneClass } from '../ui'
import StockLink from '../StockLink'
import { PageState } from '../PageState'
import { pickState } from '../stateRules'

const WORD_NAME: Record<string, string> = { TRADE: 'Buy', WATCH: 'Watch', WAIT: 'Wait', AVOID: 'Avoid' }
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

type Multi = string[]
const toggle = (list: Multi, v: string): Multi => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])

function Chips({
  label,
  options,
  value,
  onChange,
  name,
  disabled,
}: {
  label: string
  options: string[]
  value: Multi
  onChange: (v: Multi) => void
  name?: (v: string) => string
  disabled?: boolean
}) {
  if (options.length === 0) return null
  return (
    <div style={{ marginBottom: '0.5rem' }}>
      <div className="tm-stat-label">{label}</div>
      <div className="tm-toolbar">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            className="tm-btn op-chip"
            aria-pressed={value.includes(o)}
            disabled={disabled}
            onClick={() => onChange(toggle(value, o))}
          >
            {name ? name(o) : o}
          </button>
        ))}
      </div>
    </div>
  )
}

const day = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const pct = (n: number | null) => (n === null ? '—' : `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(1)}%`)

function ResultCell({ r, sealed }: { r: IdeaReportRow; sealed: boolean }) {
  if (sealed) return <span className="tm-dim">Sealed</span>
  if (r.outcome === null) return <span className="tm-dim">{r.status === 'due' ? 'Waiting for result' : 'Not finished'}</span>
  return (
    <span className={toneClass(r.return_pct ?? 0)}>
      {pct(r.return_pct)} <span className="tm-dim">· {OUTCOME_NAME[r.outcome]}</span>
    </span>
  )
}

export default function IdeaReports() {
  const [words, setWords] = useState<Multi>(['WATCH'])
  const [bands, setBands] = useState<Multi>([])
  const [horizons, setHorizons] = useState<Multi>([])
  const [moods, setMoods] = useState<Multi>([])
  const [outcomes, setOutcomes] = useState<Multi>([])
  const [currentOnly, setCurrentOnly] = useState(false)

  const q = useQuery({
    queryKey: ['ideaReport', words, bands, horizons, moods, outcomes, currentOnly],
    queryFn: () =>
      api.ideaReport({
        word: words,
        band: bands,
        horizon: horizons.map(Number),
        regime: moods,
        outcome: outcomes,
        current_only: currentOnly,
      }),
    retry: false,
    placeholderData: (prev) => prev,
  })

  // Not the owner, or the brain is off: this report does not exist for them, so show nothing.
  const state = pickState(q)
  if (state === 'forbidden' || state === 'not-found') return null

  const d = q.data
  const sealed = !!d?.seal.active
  return (
    <Card
      title="Idea reports"
      sub="Pick a word and a score range to see how many stocks, how many days have passed, and what happened."
    >
      {d && (
        <>
          <Chips label="What the brain said" options={d.options.words} value={words} onChange={setWords} name={(w) => WORD_NAME[w] ?? w} />
          <Chips label="Score" options={d.options.bands} value={bands} onChange={setBands} />
          <Chips label="Days allowed" options={d.options.horizons.map(String)} value={horizons} onChange={setHorizons} name={(h) => `${h} days`} />
          <Chips label="Market mood that day" options={d.options.regimes} value={moods} onChange={setMoods} name={(m) => MOOD_NAME[m] ?? m} />
          <Chips
            label="What happened"
            options={d.options.outcomes}
            value={outcomes}
            onChange={setOutcomes}
            name={(o) => OUTCOME_NAME[o] ?? o}
            disabled={sealed}
          />
          <label className="tm-dim" style={{ display: 'block', margin: '0.4rem 0 0.8rem' }}>
            <input type="checkbox" checked={currentOnly} onChange={(e) => setCurrentOnly(e.target.checked)} /> Only stocks that
            still have this word today
          </label>
          {sealed && (
            <p className="tm-dim" data-testid="report-sealed">
              Results are hidden while the test is running (from {d.seal.from ? day(d.seal.from) : 'its start'}), so the
              test stays fair. You can see how many stocks, the score, and the days done and left. “What happened” and
              the +8% / −4% results unlock when the test is reviewed.
            </p>
          )}
          <div className="tm-grid tm-cols-4" data-testid="report-summary" style={{ margin: '0.6rem 0' }}>
            <Stat label="Stocks" value={String(d.summary.ideas)} note={`${d.summary.still_this_word} still have this word`} />
            <Stat label="Still running" value={String(d.summary.tracking)} note="days left to go" />
            <Stat label="Finished" value={String(d.summary.finished + d.summary.due)} note={d.summary.due ? `${d.summary.due} waiting for result` : undefined} />
            <Stat
              label={sealed ? 'Results' : 'Hit +8% / −4%'}
              value={sealed ? 'Hidden' : `${d.summary.results.target} / ${d.summary.results.stop}`}
              note={sealed ? 'until the test is reviewed' : d.summary.results.avg_return_pct === null ? undefined : `average ${pct(d.summary.results.avg_return_pct)}`}
            />
          </div>
        </>
      )}
      {!d && state !== 'ready' && state !== 'empty' && <PageState kind={state} what="the idea report" error={q.error} onRetry={q.refetch} />}
      {d && d.rows.length === 0 && (
        <PageState kind="empty" reason="No stocks match these choices in the last 60 days. Try fewer filters." />
      )}
      {d && d.rows.length > 0 && (
        <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Idea report, scroll sideways to see more">
          <table className="tm-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th>Word</th>
                <th>First seen</th>
                <th>Days done / left</th>
                <th>Score then → now</th>
                <th>Market mood</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={`${r.symbol}-${r.word}-${r.entry_day}`}>
                  <td>
                    <StockLink symbol={r.symbol} />
                  </td>
                  <td>
                    {WORD_NAME[r.word] ?? r.word}
                    {!r.still_this_word && <div className="tm-dim">now {WORD_NAME[r.latest_word] ?? r.latest_word}</div>}
                  </td>
                  <td>{day(r.entry_day)}</td>
                  <td className="tm-num">
                    {r.days_done} done · {r.days_left} left <span className="tm-dim">of {r.horizon_days}</span>
                  </td>
                  <td className="tm-num">
                    {r.entry_score ?? '—'} → {r.latest_score ?? '—'}
                  </td>
                  <td>{r.regime ? MOOD_NAME[r.regime] ?? r.regime : '—'}</td>
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

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <div className="tm-stat-label">{label}</div>
      <div className="tm-stat-value">{value}</div>
      {note && <div className="tm-dim">{note}</div>}
    </div>
  )
}
