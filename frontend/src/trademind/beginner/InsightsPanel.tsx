// oa11 Insights on Records: a Day / Week / Month switch over practice money and (only for the real-account
// owner, decided by the server) real money, side by side and never added together, with two benchmarks
// after costs that each name their definition. Plus "Is the brain getting better?": the 30-idea trial count,
// the forward gate, the frozen verdicts and learning activity. Display only: nothing here trades.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { ObsClaim, ObsForwardGate, ObsLearning } from '../../api/types'
import { Seg } from '../ui'
import { NA, benchCell, bookCell, improvingAnswer } from '../insights'
import { useEvidence, useInsights } from './api'
import type { EvidenceSummary, InsightsData, InsightsPeriod } from './types'
import './beginner.css'

const PERIODS = [
  { id: 'day', label: 'Daily' },
  { id: 'week', label: 'Weekly' },
  { id: 'month', label: 'Monthly' },
] as const

function Book({ b }: { b: InsightsData['rows'][number]['paper'] }) {
  const c = bookCell(b)
  return (
    <>
      <div>{c.main}</div>
      {c.detail && <div className="bx-small">{c.detail}</div>}
    </>
  )
}

/** The table for one period length. Pure: renders exactly what the server sent. */
export function InsightsTable({ data }: { data: InsightsData }) {
  const real = data.real_shown
  return (
    <div className="tm-grid" data-testid="insights-table">
      <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
        <table className="tm-table">
          <thead>
            <tr>
              <th>Period</th>
              <th>{data.paper_label}</th>
              {real && <th data-testid="insights-real-head">{data.real_label}</th>}
              <th className="tm-right">NIFTY 50*</th>
              <th className="tm-right">Every stock the brain looked at*</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.key}>
                <td>{r.label}</td>
                <td>
                  <Book b={r.paper} />
                </td>
                {real && <td>{r.real ? <Book b={r.real} /> : NA}</td>}
                <td className="tm-right">{benchCell(r.nifty_50)}</td>
                <td className="tm-right">
                  {benchCell(r.every_stock)}
                  {r.every_stock.pct !== null && r.every_stock.stocks ? (
                    <div className="bx-small">{`${r.every_stock.stocks} stocks`}</div>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tm-note">
        <strong>{data.note}</strong>
      </p>
      <details data-testid="insights-definitions">
        <summary>How each figure is worked out</summary>
        <ul className="bx-plan">
          <li>
            <strong>{data.paper_label}:</strong> {data.definitions.paper}
          </li>
          {real && data.definitions.real && (
            <li>
              <strong>{data.real_label}:</strong> {data.definitions.real}
            </li>
          )}
          <li>
            <strong>*NIFTY 50:</strong> {data.definitions.nifty_50}
          </li>
          <li>
            <strong>*Every stock the brain looked at:</strong> {data.definitions.every_stock}
          </li>
        </ul>
        <p className="bx-small">{`Rules: ${data.defs}. Periods start at the practice trial's start (${data.since ?? 'not set'}).`}</p>
      </details>
    </div>
  )
}

export function InsightsLive() {
  const [period, setPeriod] = useState<InsightsPeriod>('week')
  const q = useInsights(period)
  return (
    <div className="tm-grid" data-testid="insights-panel">
      <Seg options={PERIODS} active={period} onChange={setPeriod} small />
      {q.isLoading && <p className="tm-note">Loading…</p>}
      {(q.isError || (!q.isLoading && !q.data)) && <p className="tm-note">{`${NA} — the figures could not be loaded`}</p>}
      {q.data && <InsightsTable data={q.data} />}
    </div>
  )
}

// ---- is the brain getting better? ----

export interface BrainProgressProps {
  trial: EvidenceSummary['brain_trial'] | null
  gate: ObsForwardGate | null
  claims: ObsClaim[] | null
  learning: ObsLearning | null
}

const sumKeys = (o: Record<string, number> | undefined) => Object.values(o ?? {}).reduce((s, n) => s + n, 0)

/** Counts, gate words and frozen verdicts only: the brain's trial results stay sealed. */
export function BrainProgress({ trial, gate, claims, learning }: BrainProgressProps) {
  const answer = improvingAnswer(claims ?? undefined)
  return (
    <section className="bx-evidence" data-testid="brain-progress">
      <p data-testid="brain-improving">
        Is the brain getting better? <strong>{answer.word}</strong>
      </p>
      <p className="bx-small">{answer.why}</p>

      <h4>Practice trial (30 finished ideas needed)</h4>
      {trial ? (
        <>
          <p data-testid="brain-trial-count">{`${trial.finished} of ${trial.needed} finished`}</p>
          <p className="tm-note">{trial.sealed_note}</p>
        </>
      ) : (
        <p className="tm-note">{`${NA} — the trial count could not be loaded`}</p>
      )}

      <h4>Forward check</h4>
      {gate ? (
        <p data-testid="brain-forward-gate">
          <strong>{gate.word}</strong> — {gate.why}
        </p>
      ) : (
        <p className="tm-note">{`${NA} — the forward check could not be loaded`}</p>
      )}

      <h4>Frozen tests</h4>
      {claims ? (
        <ul className="bx-plan" data-testid="brain-verdicts">
          {claims.map((c) => (
            <li key={c.claim}>
              {c.label}: <strong>{c.word}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="tm-note">{`${NA} — the frozen tests could not be loaded`}</p>
      )}

      <h4>Learning in the last 30 days</h4>
      {learning ? (
        <ul className="bx-plan" data-testid="brain-learning">
          <li>{`Results collected: ${learning.results_collected} (${learning.results_collected_label})`}</li>
          <li>{`Changes proposed: ${sumKeys(learning.changes_proposed)}`}</li>
          <li>{`Learning checks run: ${learning.learning_checks}`}</li>
        </ul>
      ) : (
        <p className="tm-note">{`${NA} — learning activity could not be loaded`}</p>
      )}
      <p className="bx-small">Activity is not proof of improvement: only a frozen test that passes can show that.</p>
    </section>
  )
}

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export function BrainProgressLive() {
  const evidence = useEvidence()
  const gate = useQuery({ queryKey: ['obs-forward-gate'], queryFn: api.obsForwardGate })
  const proof = useQuery({ queryKey: ['obs-eff'], queryFn: api.obsEffectiveness })
  const to = new Date()
  const from = new Date(to.getTime() - 29 * 86_400_000)
  const learning = useQuery({
    queryKey: ['obs-learning', iso(from), iso(to)],
    queryFn: () => api.obsLearning(iso(from), iso(to)),
  })
  if (evidence.isLoading || gate.isLoading || proof.isLoading || learning.isLoading) {
    return <p className="tm-note">Loading…</p>
  }
  return (
    <BrainProgress
      trial={evidence.data?.brain_trial ?? null}
      gate={gate.data ?? null}
      claims={proof.data?.claims ?? null}
      learning={learning.data ?? null}
    />
  )
}
