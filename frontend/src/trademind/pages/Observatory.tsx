// Brain Observatory (Phase 1A): what the brain stored for a date, a run and a stock. Read-only, owner only.
// Three layers never mix: did it run / was it recorded / is it proven (spec section 0).
import { useState } from 'react'
import type { ReactNode } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { ObsByKey, ObsDay, ObsModuleRow, ObsRunsCursor, ObsScoreBand } from '../../api/types'
import { Card, Tabs } from '../ui'
import { scoreBandText, withoutScorePercent } from '../scoreText'
import { PageState, StaleNotice } from '../PageState'
import { errorStatus, pickState, type QueryLike } from '../stateRules'

const TABS = ['Decision flow', 'Module activity', 'Results & proof'] as const
const FIGURES = [
  ['candidate', 'Brain TRADE ideas'],
  ['every_stock', 'Every stock (random baseline)'],
  ['random_5', 'Random 5 a day'],
  ['momentum_5', 'Momentum 5 a day'],
  ['nifty_matched', "NIFTY over each idea's own holding days"],
  ['cash', 'Cash'],
] as const
type Tab = (typeof TABS)[number]

// One column per flag; the last two are the states a run can have for a module that is simply not there.
const FLAG_COLUMNS: (keyof ObsModuleRow['flags'])[] = [
  'expected', 'executed', 'valid_output', 'used', 'shadow', 'switched_off', 'failed', 'not_observed',
  'not_applicable', 'not_installed_then', 'unknown', 'unknown_module', 'duplicate', 'conflicting',
]
const FLAG_LABEL: Record<string, string> = {
  not_installed_then: 'not installed then',
  unknown: 'unknown (no module list)',
  unknown_module: 'unknown module',
}
const NIGHTLY_WORD: Record<string, string> = {
  observed: 'Ran', not_observed: 'Not observed', not_due: 'Not due yet', not_applicable: 'Not applicable (no trading)',
  conflicting: 'Conflicting records', failed: 'Started and failed', in_progress: 'Not finished yet',
}
const IDEA_WORDS = ['TRADE', 'WATCH', 'WAIT', 'AVOID'] as const
const DEFERRED = 'Not recorded — decision-path recording deferred during trial'
const INFLUENCE = 'Influence on this stock: Not recorded in Phase 1A.'
const PROOF_LABEL = 'Observed, not proof'
const DAY_ROWS = 14 // the selected day plus the 13 trading days before it

function todayIst(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date())
}

function shiftDay(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function monthRange(iso: string): { from: string; to: string } {
  const y = Number(iso.slice(0, 4))
  const m = Number(iso.slice(5, 7))
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return { from: `${iso.slice(0, 7)}-01`, to: `${iso.slice(0, 7)}-${String(last).padStart(2, '0')}` }
}

function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? '—' : `${(x * 100).toFixed(2)}%`
}

function keyed(o: ObsByKey | undefined | null): string {
  const e = Object.entries(o ?? {})
  return e.length ? e.map(([k, v]) => `${k} ${v}`).join(', ') : '—'
}

function Redacted({ fields }: { fields?: string[] }) {
  return fields && fields.length ? <p className="tm-dim">Some text is hidden for safety ({fields.length}).</p> : null
}

// Every card's request state: loading, an explicit error (never a blank card) with "Try again", or an empty
// message. Drawn by the shared PageState; a failed refetch keeps the loaded data and shows the stale notice.
// The server's own words stay under the plain sentence: this is the owner's diagnostic screen.
function QueryState({
  q, empty, id,
}: { q: QueryLike & { refetch?: () => unknown }; empty?: string; id: string }) {
  const kind = pickState(q)
  if (kind === 'loading' || kind === 'offline') {
    return <div data-testid={`obs-loading-${id}`}><PageState kind={kind} what="this" /></div>
  }
  if (kind !== 'ready' && kind !== 'empty') {
    const e = q.error
    const status = errorStatus(e)
    return (
      <div data-testid="obs-error" data-obs-error-for={id}>
        <PageState kind={kind === 'not-found' ? 'error' : kind} what="this" error={e} onRetry={q.refetch} />
        <p className="tm-note">
          Server said{status ? ` (${status})` : ''}: {e instanceof Error ? e.message : String(e)}
        </p>
      </div>
    )
  }
  return (
    <>
      <StaleNotice q={q} />
      {empty ? <div data-testid={`obs-empty-${id}`}><PageState kind="empty" reason={empty} /></div> : null}
    </>
  )
}

function DayRow({ d, selected }: { d: ObsDay; selected: boolean }) {
  const idea = d.counts?.idea ?? {}
  const intraday = d.intraday
  const intradayText = intraday.not_applicable
    ? 'Not applicable'
    : `${String(intraday.recorded ?? 0)} recorded / ${String(intraday.due ?? '—')} due (of ${String(intraday.slots ?? '—')})`
  return (
    <tr data-testid="obs-day-row" data-day={d.day} className={selected ? 'tm-selected' : undefined}>
      <td>{d.day}{selected ? ' (selected)' : ''}</td>
      <td>{NIGHTLY_WORD[d.nightly.state] ?? d.nightly.state}</td>
      <td className="tm-right">{d.universe ?? '—'}</td>
      <td className="tm-right">{d.counts ? d.counts.ideas_total : '—'}</td>
      <td className="tm-right">{d.counts ? d.counts.holdings_total : '—'}</td>
      {IDEA_WORDS.map((w) => <td key={w} className="tm-right">{d.counts ? (idea[w] ?? 0) : '—'}</td>)}
      <td>{keyed(d.tracked.by_book)}</td>
      <td>{keyed(d.signals.by_mode)}</td>
      <td>{keyed(d.paper_orders.by_mode)}</td>
      <td>{intradayText}</td>
    </tr>
  )
}

export default function Observatory() {
  const [day, setDay] = useState(todayIst())
  const [runId, setRunId] = useState<string>('')
  const [symbol, setSymbol] = useState('')
  const [decisionId, setDecisionId] = useState<number | null>(null)
  const [tab, setTab] = useState<Tab>('Decision flow')

  const runs = useInfiniteQuery({
    queryKey: ['obs-runs', day],
    queryFn: ({ pageParam }) => api.obsRunsPage(day, pageParam?.after_started_at, pageParam?.after_id),
    initialPageParam: undefined as ObsRunsCursor | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const runItems = runs.data?.pages.flatMap((p) => p.items) ?? []
  const nightly = runs.data?.pages[0]?.nightly
  const chosenRun = runId || nightly?.run_id || runItems[0]?.id || ''

  const run = useQuery({ queryKey: ['obs-run', chosenRun], queryFn: () => api.obsRun(chosenRun), enabled: !!chosenRun })
  const stocks = useInfiniteQuery({
    queryKey: ['obs-stocks', chosenRun, symbol],
    queryFn: ({ pageParam }) => api.obsStocks(chosenRun, symbol || undefined, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_cursor?.after_id,
    enabled: !!chosenRun,
  })
  const stockItems = stocks.data?.pages.flatMap((p) => p.items) ?? []
  const stock = useQuery({
    queryKey: ['obs-stock', chosenRun, decisionId],
    queryFn: () => api.obsStock(chosenRun, decisionId as number),
    enabled: !!chosenRun && decisionId !== null,
  })
  const proof = useQuery({ queryKey: ['obs-eff'], queryFn: api.obsEffectiveness })
  // The official gate never depends on the date picker: no day in the key, no day in the call.
  const gate = useQuery({ queryKey: ['obs-forward-gate'], queryFn: api.obsForwardGate })
  const month = monthRange(day)
  const days = useQuery({
    queryKey: ['obs-days', day],
    queryFn: () => api.obsDays(shiftDay(day, -24), day),
  })
  const learning = useQuery({
    queryKey: ['obs-learning', month.from, month.to],
    queryFn: () => api.obsLearning(month.from, month.to),
    enabled: tab === 'Results & proof',
  })
  const bands = useQuery({
    queryKey: ['obs-score-bands', day],
    queryFn: () => api.obsScoreBands(shiftDay(day, -91), day),
    enabled: tab === 'Results & proof',
  })
  const results = useQuery({
    queryKey: ['obs-outcomes', month.from, day],
    queryFn: () => api.obsOutcomes(month.from, day, 'practice'),
    enabled: tab === 'Results & proof',
  })

  const r = run.data
  const ranking = proof.data?.claims.filter((c) => c.claim.startsWith('model_ranking')) ?? []
  const fullBrain = proof.data?.claims.find((c) => c.claim === 'full_brain')
  // Selected day plus the 13 trading days before it, newest first. Non-trading days carry no nightly run.
  const dayRows = (days.data?.days ?? [])
    .filter((d) => d.day === day || d.nightly.state !== 'not_applicable')
    .slice(-DAY_ROWS)
    .reverse()

  const pickDay = (v: string) => { if (v) { setDay(v); setRunId(''); setDecisionId(null) } }

  return (
    <div className="tm-page tm-grid" data-testid="obs-page">
      <Card title="Brain Observatory" sub="Owner only · Paper mode · Read-only">
        <div className="tm-toolbar">
          <label>Date{' '}
            <input className="tm-input" type="date" data-testid="obs-date" value={day} onChange={(e) => pickDay(e.target.value)} />
          </label>
          <label>Run{' '}
            <select className="tm-select" data-testid="obs-run-select" value={chosenRun}
              onChange={(e) => { setRunId(e.target.value); setDecisionId(null) }}>
              {runItems.map((x) => (
                <option key={x.id} value={x.id}>{x.kind} · {x.status} · {x.started_at?.slice(11, 16)} UTC</option>
              ))}
            </select>
          </label>
          {runs.hasNextPage && (
            <button type="button" className="tm-btn tm-btn-ghost" data-testid="obs-runs-load-more"
              disabled={runs.isFetchingNextPage} onClick={() => runs.fetchNextPage()}>
              {runs.isFetchingNextPage ? 'Loading…' : 'Load more runs'}
            </button>
          )}
          <label>Stock{' '}
            <input className="tm-input" data-testid="obs-symbol" value={symbol} placeholder="e.g. INFY"
              onChange={(e) => { setSymbol(e.target.value); setDecisionId(null) }} />
          </label>
        </div>
        <QueryState q={runs} id="runs" empty={runs.data && runItems.length === 0 ? 'No runs on this day' : undefined} />
        {nightly && (
          <p data-testid="obs-nightly">Nightly run this day: <b>{NIGHTLY_WORD[nightly.state] ?? nightly.state}</b></p>
        )}
      </Card>

      <div className="tm-grid tm-cols-3">
        <Card title="1 / Did the brain run?" sub="Run health" className="" >
          <div data-testid="obs-card-ran">
            {r ? (
              <>
                <h3>{r.headline === 'completed' ? 'Completed' : r.headline === 'degraded' ? 'Completed with problems' : r.headline}</h3>
                <p>{Math.round(r.run.ms / 1000)} s · {String(r.counts.used)} modules used · {String(r.counts.failed)} failed ·{' '}
                  {String(r.counts.not_observed)} not observed (inferred)</p>
                {r.run.error && <p className="tm-neg">{r.run.error}</p>}
              </>
            ) : chosenRun ? <QueryState q={run} id="run" /> : <QueryState q={runs} id="run-none" empty="No run selected." />}
          </div>
        </Card>
        <Card title="2 / Was it recorded?" sub="Recording health">
          <div data-testid="obs-card-recorded">
            {r ? (
              <>
                <h3 data-testid="obs-recorded-heading">{r.recording.card}</h3>
                <ul>{r.recording.not_recorded.map((x) => <li key={x}>{x}</li>)}</ul>
              </>
            ) : (
              <>
                <h3 data-testid="obs-recorded-heading">Existing records only — partial visibility.</h3>
                {chosenRun && <QueryState q={run} id="recorded" />}
              </>
            )}
            <p className="tm-dim">A complete record would still say nothing about whether decisions were good.</p>
          </div>
        </Card>
        <Card title="3 / Is it proven to help?" sub="Effectiveness: frozen tests only">
          <div data-testid="obs-card-proven">
            <QueryState q={proof} id="proof" empty={proof.data && !ranking.length && !fullBrain ? 'No verdicts available.' : undefined} />
            {ranking.map((c) => <p key={c.claim} data-testid="obs-verdict" data-claim={c.claim}><b>{c.word}</b> — {c.label}</p>)}
            {fullBrain && <p data-testid="obs-verdict" data-claim={fullBrain.claim}><b>{fullBrain.word}</b> — {fullBrain.label}</p>}
            {ranking[0]?.independence_note && <p className="tm-dim">{ranking[0].independence_note}</p>}
            <div data-testid="obs-forward-gate">
              <h4>Official forward gate</h4>
              <QueryState q={gate} id="gate" />
              {gate.data && (
                <>
                  <p data-testid="obs-forward-gate-word"><b>{gate.data.word}</b> — {gate.data.why}</p>
                  {gate.data.gate && (
                    <p>{gate.data.gate.sessions} sessions, {gate.data.gate.finished} finished: {gate.data.gate.word}</p>
                  )}
                  <p className="tm-dim" data-testid="obs-forward-gate-cohort">
                    Cohort {gate.data.cohort_from} to {gate.data.cohort_to}: {gate.data.cohort}. Does not change with the date picker.
                  </p>
                </>
              )}
            </div>
          </div>
        </Card>
      </div>

      <Card title="Daily counts" sub={`The selected day and the 13 trading days before it. Tracked holdings are by book, signals and paper orders by mode; none are summed or linked to a run.`}>
        <QueryState q={days} id="days" empty={days.data && dayRows.length === 0 ? 'No days in range' : undefined} />
        {dayRows.length > 0 && (
          <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
            <table className="tm-table" data-testid="obs-day-counts">
              <thead>
                <tr>
                  <th>Day</th><th>Nightly</th><th>Universe</th><th>Ideas</th><th>Holdings</th>
                  {IDEA_WORDS.map((w) => <th key={w}>{w}</th>)}
                  <th>Tracked (by book)</th><th>Signals (by mode)</th><th>Paper orders (by mode)</th><th>Intraday</th>
                </tr>
              </thead>
              <tbody>{dayRows.map((d) => <DayRow key={d.day} d={d} selected={d.day === day} />)}</tbody>
            </table>
          </div>
        )}
        <Redacted fields={days.data?.redacted_fields} />
      </Card>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Decision flow' && (
        <div className="tm-grid tm-cols-2" data-testid="obs-tab-flow">
          <Card title="Stocks in this run" sub="Stored final words">
            <QueryState q={stocks} id="stocks"
              empty={chosenRun ? (stocks.data && stockItems.length === 0 ? 'No stocks stored for this run' : undefined) : 'No run selected.'} />
            <ul data-testid="obs-stocks-list">
              {stockItems.map((s) => (
                <li key={s.id}>
                  <button type="button" className="tm-link" data-testid="obs-stock-item" data-symbol={s.symbol}
                    onClick={() => setDecisionId(s.id)}>{s.symbol} · {s.kind} · <b>{s.word}</b></button>
                </li>
              ))}
            </ul>
            {stocks.hasNextPage && (
              <button type="button" className="tm-btn tm-btn-ghost" data-testid="obs-load-more"
                disabled={stocks.isFetchingNextPage} onClick={() => stocks.fetchNextPage()}>
                {stocks.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </button>
            )}
          </Card>
          {decisionId === null ? (
            <Card title="Pick a stock" sub="Choose one from the list" />
          ) : stock.data ? (
            <Card title={`${stock.data.decision.symbol} · ${stock.data.decision.kind}`} sub="Stored final decision">
              <div data-testid="obs-stock-detail">
                <h3>{stock.data.decision.word}</h3>
                <h4>Reasons (stored text)</h4>
                <ul>{stock.data.decision.reasons.map((x, i) => <li key={i}>{withoutScorePercent(x)}</li>)}</ul>
                {stock.data.decision.downgraded_from && (
                  <p>Was {stock.data.decision.downgraded_from}; last downgrade reason: {stock.data.decision.downgrade_reason && withoutScorePercent(stock.data.decision.downgrade_reason)}
                    <br /><span className="tm-dim">{stock.data.decision.downgrade_label}</span></p>
                )}
                <h4>Recorded decision path</h4>
                <p className="tm-dim" data-testid="obs-decision-path">{DEFERRED}</p>
                <h4>Why no TRADE?</h4>
                <p className="tm-dim" data-testid="obs-why-no-trade">{DEFERRED}</p>
                <h4>Module opinions, risk verdict, sector used</h4>
                <p className="tm-dim">{stock.data.not_recorded.opinions}</p>
                <p className="tm-dim" data-testid="obs-influence">{INFLUENCE}</p>
                <h4>Model inputs at decision time</h4>
                {stock.data.features.state === 'observed'
                  ? <p>Close ₹{stock.data.features.close} on {stock.data.features.bar_date}</p>
                  : <p className="tm-dim">Not observed — {stock.data.features.why}</p>}
                {stock.data.decision.outcome && (stock.data.decision.outcome.sealed ? (
                  <p data-testid="obs-stock-outcome-sealed">Outcome: finished. {stock.data.decision.outcome.source}</p>
                ) : (
                  <p>Outcome: {stock.data.decision.outcome.outcome}, {pct(stock.data.decision.outcome.gross_return)} gross
                    <br /><span className="tm-dim">{stock.data.decision.outcome.source}</span></p>
                ))}
                <p className="tm-dim">
                  {stock.data.tracker.label}{stock.data.tracker.book ? ` (book: ${stock.data.tracker.book})` : ''}: {stock.data.tracker.rows.length} record(s)
                </p>
                <p className="tm-dim">{stock.data.instrument.label}: {stock.data.instrument.current.map((i) => i.exchange).join(', ') || 'none'}</p>
                <Redacted fields={stock.data.redacted_fields} />
              </div>
            </Card>
          ) : (
            <Card title="Stock detail"><QueryState q={stock} id="stock" /></Card>
          )}
        </div>
      )}

      {tab === 'Module activity' && (
        <Card title="Module activity" sub="Per run. Expected / not observed / not applicable are inferred from the run's own module list and the current module list.">
          {!chosenRun && <QueryState q={runs} id="modules-none" empty="No run selected." />}
          {chosenRun && !r && <QueryState q={run} id="modules" />}
          {r && (
            <>
              <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
                <table className="tm-table" data-testid="obs-modules-table">
                  <thead>
                    <tr>
                      <th>Module</th><th>Step</th>
                      {FLAG_COLUMNS.map((f) => <th key={f}>{FLAG_LABEL[f] ?? f.replace(/_/g, ' ')}</th>)}
                      <th>Records</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.modules.map((m) => (
                      <ModuleRows key={m.module_id} m={m} />
                    ))}
                    {r.outside_steps.map((o) => (
                      <tr key={o.module_id} data-testid="obs-outside-row" data-module={o.module_id}>
                        <td>{o.module_id}</td>
                        <td colSpan={FLAG_COLUMNS.length + 2}>{o.state.replace(/_/g, ' ')} — {o.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="tm-dim">* inferred, not recorded by this run.</p>
              {r.step_fallbacks.length > 0 && (
                <p className="tm-dim">Step fallbacks: {r.step_fallbacks.map((f) => `${f.step} (${f.reason})`).join('; ')}</p>
              )}
              <p data-testid="obs-universe-relation">Universe {r.universe_relation.universe ?? '—'} · idea decisions {r.universe_relation.ideas} · holding decisions{' '}
                {r.universe_relation.holdings} — {r.universe_relation.state === 'conflicting' ? 'Conflicting records' :
                  r.universe_relation.state === 'not_observed' ? 'Not observed' : 'within the possible range; nothing more is claimed'}</p>
              <Redacted fields={r.redacted_fields} />
            </>
          )}
        </Card>
      )}

      {tab === 'Results & proof' && (
        <div className="tm-grid tm-cols-2" data-testid="obs-tab-results">
          <Card title="Results this month: what happened, compared with what" sub={PROOF_LABEL}>
            <QueryState q={results} id="results" />
            {results.data && (
              <div data-testid="obs-results">
                <p className="tm-dim" data-testid="obs-observed-not-proof">{PROOF_LABEL}{results.data.label ? ` — ${results.data.label}` : ''}</p>
                {results.data.sealed && (
                  <p data-testid="obs-results-sealed">
                    <b>Trial days {results.data.sealed.from} to {results.data.sealed.to}</b>: {results.data.sealed.text}{' '}
                    {results.data.sealed.sessions} session(s), {results.data.sealed.trade_ideas} TRADE idea(s),{' '}
                    {results.data.sealed.graded} graded idea(s) of every word ({results.data.sealed.graded_trade} TRADE).
                    <br />
                    <span className="tm-dim">
                      {results.data.results_period
                        ? `The figures below cover only ${results.data.results_period.from} to ${results.data.results_period.to}, before the trial started.`
                        : 'No days before the trial in this range, so there are no figures below.'}
                    </span>
                  </p>
                )}
                <div data-testid="obs-stored-grades">
                  <p>
                    Stored grades, all ideas of every word (gross): {results.data.stored_grades.available
                      ? `${results.data.stored_grades.count} ideas, average ${pct(results.data.stored_grades.avg_gross_return)} gross`
                      : `Not available — ${results.data.stored_grades.why ?? ''}`}
                  </p>
                  <p data-testid="obs-stored-grades-trade">
                    Of those, ideas the brain said TRADE: {results.data.stored_grades.trade?.available
                      ? `${results.data.stored_grades.trade.count} ideas, average ${pct(results.data.stored_grades.trade.avg_gross_return)} gross`
                      : `Not available — ${results.data.stored_grades.trade?.why ?? 'no graded TRADE ideas'}`}
                  </p>
                  <p className="tm-dim">{results.data.stored_grades.all_words_note}</p>
                  <p className="tm-dim">{results.data.stored_grades.source}</p>
                </div>
                <p className="tm-dim">Category: {results.data.category} (live practice-stage ideas only; never mixed with backtests or v1 paper trades)</p>
                {results.data.excluded && (
                  <p className="tm-dim" data-testid="obs-excluded">
                    Excluded, not mixed in: {results.data.excluded.other_stage_days} day(s) in another stage, {results.data.excluded.other_book_runs} run(s) in another book.
                  </p>
                )}
                {FIGURES.map(([k, label]) => {
                  const f = results.data.computed[k]
                  if (!f) {
                    return (
                      <p key={k} data-testid="obs-figure" data-figure={k}>
                        <b>{label}</b>: Not available — this figure was not returned.
                      </p>
                    )
                  }
                  const value = k === 'random_5' ? f.avg_net_mean : f.avg_net
                  return (
                    <p key={k} data-testid="obs-figure" data-figure={k}>
                      <b>{label}</b>: {f.available ? pct(value) : `Not available — ${f.why ?? ''}`}
                      {f.available && k === 'random_5' && f.beaten_share != null && (
                        <> · beaten by the brain in {Math.round(f.beaten_share * 100)}% of {f.draws} draws</>
                      )}
                      <br /><span className="tm-dim">{f.source}</span>
                    </p>
                  )
                })}
                {results.data.computed.edge && (
                  <p data-testid="obs-figure" data-figure="edge">
                    <b>Brain minus every stock, per day</b>:{' '}
                    {results.data.computed.edge.available
                      ? `${pct(results.data.computed.edge.mean)} (lower bound ${pct(results.data.computed.edge.lower_bound)}; ${results.data.computed.edge.word})`
                      : `Not available — ${results.data.computed.edge.why ?? ''}`}
                    <br /><span className="tm-dim">{results.data.computed.edge.source}</span>
                  </p>
                )}
                <p className="tm-dim">Costs: {results.data.computed.costs}</p>
              </div>
            )}
          </Card>
          <Card title="Does a higher score really mean better results?" sub="How often +8% came before -4%, by the score the idea had">
            <div data-testid="obs-score-bands">
              <QueryState q={bands} id="score-bands" />
              {bands.data && (
                <>
                  <p className="tm-dim">If the bars are about the same height, the score is not telling good ideas from bad ones.</p>
                  <h4>Tested on past data ({bands.data.development.period})</h4>
                  <ScoreBars rows={bands.data.development.bands} />
                  <p className="tm-dim">{bands.data.development.note}</p>
                  {bands.data.live.map((part) => (
                    <div key={part.period} data-testid="obs-score-bands-live" data-period={part.period}>
                      <h4>{part.period === 'trial' ? 'The trial so far' : 'Before the trial'} ({part.from} to {part.to})</h4>
                      <p className="tm-dim">{part.label}</p>
                      <ScoreBars rows={part.bands} sealed={part.sealed} />
                    </div>
                  ))}
                  <p className="tm-dim">Rule: {bands.data.rule}</p>
                </>
              )}
            </div>
          </Card>
          <Card title="Is it proven?" sub="Only frozen, independent tests count">
            <QueryState q={proof} id="proof-tab" empty={proof.data && proof.data.claims.length === 0 ? 'No verdicts available.' : undefined} />
            {(proof.data?.claims ?? []).map((c) => (
              <div key={c.claim} data-testid="obs-claim" data-claim={c.claim}>
                <p><b>{c.word}</b> — {c.label}</p>
                {c.numbers && (
                  <p className="tm-dim">
                    Numbers: {c.numeric} ({String(c.numbers.folds_won)} of {String(c.numbers.eligible_folds)} windows) · independence: {c.independence}
                  </p>
                )}
                {c.tested_subject && <p className="tm-dim">{c.tested_subject}</p>}
                {c.problems.length > 0 && <p className="tm-neg">{c.problems.join('; ')}</p>}
              </div>
            ))}
          </Card>
          <Card title={`Learning · ${month.from.slice(0, 7)}`} sub="Only M09 activity counts as learning">
            <div data-testid="obs-learning">
              <QueryState q={learning} id="learning" />
              {learning.data && (
                <>
                  <p>Results collected: <b>{learning.data.results_collected}</b> <span className="tm-dim">({learning.data.results_collected_label})</span></p>
                  <p>Changes proposed (by status): {keyed(learning.data.changes_proposed)}</p>
                  <p>Learning checks: <b>{learning.data.learning_checks}</b></p>
                  <p><b>{learning.data.proven_improvement.word}</b> — {learning.data.proven_improvement.label}</p>
                  <p className="tm-dim">Only M09 activity counts as learning. {learning.data.note}</p>
                  <Redacted fields={learning.data.redacted_fields} />
                </>
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}

function ScoreBars({ rows, sealed = false }: { rows: ObsScoreBand[]; sealed?: boolean }) {
  // Bars fill to a 50% hit rate; the +8%-first rate needed to break even is about 33%.
  return (
    <div data-testid="obs-score-bars">
      {rows.map((b) => {
        const shown = !sealed && b.hit_rate != null
        const width = shown ? Math.min(100, ((b.hit_rate as number) / 0.5) * 100) : 0
        const text = sealed
          ? `${b.ideas} ideas · ${b.finished ?? 0} finished`
          : shown
            ? `${Math.round((b.hit_rate as number) * 100)}% of ${b.finished ?? b.ideas} ideas`
            : `${b.ideas} ideas · none finished`
        return (
          <div key={b.band} className="tm-hbar" style={{ gridTemplateColumns: '110px 1fr 150px' }} data-band={b.band}>
            <span className="tm-dim">Score {scoreBandText(b.band)}</span>
            <div className="tm-hbar-track">
              <div className="tm-hbar-fill tm-violet" style={{ width: `${width}%` }} />
            </div>
            <span className="tm-right tm-num">{text}</span>
          </div>
        )
      })}
    </div>
  )
}

function ModuleRows({ m }: { m: ObsModuleRow }): ReactNode {
  return (
    <>
      <tr data-testid="obs-module-row" data-module={m.module_id}>
        <td>{m.module_id}</td>
        <td>{m.step ?? '—'}{m.step_source === 'current code (inferred)' ? ' *' : ''}</td>
        {FLAG_COLUMNS.map((f) => (
          <td key={f} data-flag={f} data-on={m.flags[f] ? 'true' : 'false'}>{m.flags[f] ? (m.inferred?.[f] ? '✓*' : '✓') : ''}</td>
        ))}
        <td>{m.corroboration.replace(/_/g, ' ')}{m.conflicts.length ? `: ${m.conflicts.join('; ')}` : ''}</td>
      </tr>
      {m.failure_messages.length > 0 && (
        <tr data-testid="obs-failure-row" data-module={m.module_id}>
          <td />
          <td colSpan={FLAG_COLUMNS.length + 2} className="tm-wrap tm-neg">
            {m.failure_messages.map((x, i) => <div key={i}>{x}</div>)}
          </td>
        </tr>
      )}
    </>
  )
}
