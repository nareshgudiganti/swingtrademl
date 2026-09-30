import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, api } from '../api/client'
import type {
  BrainDecision,
  BrainModuleInfo,
  BrainTraceEvent,
  HoldingWord,
  IdeaWord,
  MarketMode,
  ModuleMode,
} from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import Modal from '../components/Modal'
import { formatCurrency, formatDateTime } from '../lib/format'

/* The brain console (build book module M17). Everything here is in plain
 * words: the brain only suggests and records; it never places an order. */

const STEP_LABEL: Record<string, string> = {
  perceive: '1 · Look at the data',
  state: '2 · Read the market',
  recognise: '3 · Recognise the situation',
  remember: '4 · Remember similar times',
  reason: '5 · Form an opinion',
  risk: '6 · Safety check',
  decide: '7 · Decide',
  learn: '8 · Learn from results',
}

const MODE_LABEL: Record<ModuleMode, string> = { on: 'On', shadow: 'Trial', off: 'Off' }

const MARKET: Record<MarketMode, { label: string; className: string; plain: string }> = {
  NORMAL: { label: 'NORMAL', className: 'banner-ok', plain: 'New ideas are allowed at full size.' },
  DEFENSIVE: {
    label: 'DEFENSIVE',
    className: 'banner-warn',
    plain: 'Careful market: at most two new ideas, at half size.',
  },
  NO_NEW_TRADES: {
    label: 'NO NEW TRADES',
    className: 'banner-warn',
    plain: 'No new buys today. Stocks you hold are still watched and sold as usual.',
  },
}

const WORD_BADGE: Record<string, string> = {
  TRADE: 'badge-buy',
  WATCH: 'badge-watch',
  WAIT: 'badge-hold',
  AVOID: 'badge-sell',
  HOLD: 'badge-on',
  MONITOR: 'badge-watch',
  REDUCE: 'badge-warn',
  EXIT: 'badge-exit',
}

const WORD_PLAIN: Record<string, string> = {
  TRADE: 'A planned buy with a size, target and stop',
  WATCH: 'Interesting, but something is blocking it',
  WAIT: 'No reason to act right now',
  AVOID: 'Stay away for a stated reason',
  HOLD: 'Keep it; the plan is working',
  MONITOR: 'Keep it, but watch closely',
  REDUCE: 'Take some off',
  EXIT: 'Leave the position',
}

// Most careful first, the same order the brain uses.
const IDEA_ORDER: IdeaWord[] = ['AVOID', 'WAIT', 'WATCH', 'TRADE']
const HOLDING_ORDER: HoldingWord[] = ['EXIT', 'REDUCE', 'MONITOR', 'HOLD']

function finalWord(d: BrainDecision): string {
  return d.overruled_word ?? d.word
}

function moreCareful(d: BrainDecision): string[] {
  const order: string[] = d.kind === 'idea' ? IDEA_ORDER : HOLDING_ORDER
  return order.slice(0, order.indexOf(finalWord(d)))
}

function WordPill({ word }: { word: string }) {
  return (
    <span className={`badge ${WORD_BADGE[word] ?? 'badge-off'}`} title={WORD_PLAIN[word]}>
      {word}
    </span>
  )
}

function traceLine(e: BrainTraceEvent): string {
  if (e.module_id === 'fallback') return 'Simple built-in answer (no module installed for this step)'
  switch (e.status) {
    case 'used':
      return `${e.module_id} answered`
    case 'shadow':
      return `${e.module_id} ran on trial — recorded, not used`
    case 'skipped':
      return `${e.module_id} is switched off`
    case 'rejected':
      return `${e.module_id}'s answer was refused: ${e.reason}`
    default:
      return `${e.module_id} did not answer (${e.reason}); the simple built-in answer was used`
  }
}

function HowItDecided({ trace }: { trace: BrainTraceEvent[] }) {
  const steps = Array.from(new Set(trace.map((e) => e.step)))
  return (
    <ol className="brain-steps">
      {steps.map((step) => (
        <li key={step}>
          <strong>{STEP_LABEL[step] ?? step}</strong>
          <ul>
            {trace
              .filter((e) => e.step === step)
              .map((e, i) => (
                <li key={i} className="muted">
                  {traceLine(e)}
                </li>
              ))}
          </ul>
        </li>
      ))}
    </ol>
  )
}

function DecisionDetail({
  decision,
  trace,
  onOverruled,
}: {
  decision: BrainDecision
  trace: BrainTraceEvent[] | undefined
  onOverruled: () => void
}) {
  const options = moreCareful(decision)
  const [word, setWord] = useState(options[options.length - 1] ?? '')
  const [reason, setReason] = useState('')
  const overrule = useMutation({
    mutationFn: () => api.brainOverrule(decision.id, word, reason),
    onSuccess: onOverruled,
  })

  return (
    <>
      <div className="between">
        <h2 style={{ margin: 0 }}>{decision.symbol}</h2>
        <WordPill word={finalWord(decision)} />
      </div>
      <p className="muted" style={{ marginTop: '0.3rem' }}>
        {WORD_PLAIN[finalWord(decision)]}
      </p>

      {decision.overruled_word && (
        <div className="banner banner-info" style={{ margin: '0.6rem 0' }}>
          You changed this from {decision.word} to {decision.overruled_word}: “{decision.overrule_reason}”
        </div>
      )}

      {finalWord(decision) === 'TRADE' && decision.entry_low != null && (
        <div className="grid brain-levels">
          <div>
            <div className="stat-sub">Buy around</div>
            <strong>{formatCurrency(decision.entry_low)}</strong>
          </div>
          <div>
            <div className="stat-sub">Target (+8%)</div>
            <strong>{decision.target != null ? formatCurrency(decision.target) : '—'}</strong>
          </div>
          <div>
            <div className="stat-sub">Stop (−4%)</div>
            <strong>{decision.stop != null ? formatCurrency(decision.stop) : '—'}</strong>
          </div>
          <div>
            <div className="stat-sub">Shares</div>
            <strong>{decision.qty}</strong>
          </div>
        </div>
      )}

      <h3>Why</h3>
      <ul className="brain-reasons">
        {decision.reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>

      <h3>How the brain decided</h3>
      {trace ? <HowItDecided trace={trace} /> : <Loading />}

      {options.length > 0 && (
        <>
          <h3>Overrule</h3>
          <p className="stat-sub">You can only make the brain more careful, and you must say why.</p>
          <div className="brain-overrule">
            <select value={word} onChange={(e) => setWord(e.target.value)} aria-label="New decision">
              {options.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why? e.g. results next week"
              aria-label="Reason"
            />
            <button
              className="primary"
              disabled={!reason.trim() || overrule.isPending}
              onClick={() => overrule.mutate()}
            >
              {overrule.isPending ? 'Saving…' : 'Overrule'}
            </button>
          </div>
          {overrule.isError && <ErrorBox error={overrule.error} />}
        </>
      )}
    </>
  )
}

function DecisionRow({ d, onOpen }: { d: BrainDecision; onOpen: () => void }) {
  return (
    <tr onClick={onOpen} style={{ cursor: 'pointer' }}>
      <td>
        <strong>{d.symbol}</strong>
      </td>
      <td>
        <WordPill word={finalWord(d)} />
        {d.overruled_word && <div className="stat-sub">brain said {d.word}</div>}
      </td>
      <td className="brain-reason-cell">
        {d.reasons[0]}
        {finalWord(d) === 'TRADE' && d.entry_low != null && (
          <div className="stat-sub">
            {d.qty} shares near {formatCurrency(d.entry_low)} · target{' '}
            {d.target != null ? formatCurrency(d.target) : '—'} · stop {d.stop != null ? formatCurrency(d.stop) : '—'}
          </div>
        )}
      </td>
      <td>
        <button onClick={(e) => (e.stopPropagation(), onOpen())}>Why?</button>
      </td>
    </tr>
  )
}

function ModuleSwitch({ m, onChange }: { m: BrainModuleInfo; onChange: (mode: ModuleMode) => void }) {
  if (m.mandatory) {
    return <span className="badge badge-on" title="The safety check can never be switched off">Always on</span>
  }
  return (
    <div className="brain-switch" role="group" aria-label={`${m.name} mode`}>
      {(['on', 'shadow', 'off'] as ModuleMode[]).map((mode) => (
        <button key={mode} className={m.mode === mode ? 'primary' : ''} onClick={() => onChange(mode)}>
          {MODE_LABEL[mode]}
        </button>
      ))}
    </div>
  )
}

export default function Brain() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState<BrainDecision | null>(null)
  const [showQuiet, setShowQuiet] = useState(false)
  const [whySymbol, setWhySymbol] = useState('')

  const latest = useQuery({
    queryKey: ['brainLatest'],
    queryFn: () => api.brainLatestRun('nightly'),
    retry: false,
  })
  const health = useQuery({ queryKey: ['brainHealth'], queryFn: api.brainHealth })
  const modules = useQuery({ queryKey: ['brainModules'], queryFn: api.brainModules })
  const runs = useQuery({ queryKey: ['brainRuns'], queryFn: () => api.brainRuns(8) })
  const trace = useQuery({
    queryKey: ['brainTrace', latest.data?.run_id],
    queryFn: () => api.brainRunTrace(latest.data!.run_id),
    enabled: !!latest.data,
  })

  const refreshAll = () => {
    for (const key of ['brainLatest', 'brainHealth', 'brainRuns', 'brainModules', 'brainTrace']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
  }
  const runNow = useMutation({ mutationFn: api.brainRunNow, onSuccess: refreshAll })
  const setMode = useMutation({
    mutationFn: ({ id, mode }: { id: string; mode: ModuleMode }) => api.setBrainModuleMode(id, mode),
    onSuccess: refreshAll,
  })
  const why = useMutation({ mutationFn: (symbol: string) => api.brainWhy(symbol) })

  const noRunYet = latest.error instanceof ApiError && latest.error.status === 404
  const run = latest.data
  const decisions = run?.decisions ?? []
  const holdings = decisions.filter((d) => d.kind === 'holding')
  const ideas = decisions.filter((d) => d.kind === 'idea')
  const active = ideas.filter((d) => ['TRADE', 'WATCH'].includes(finalWord(d)))
  const quiet = ideas.filter((d) => !['TRADE', 'WATCH'].includes(finalWord(d)))
  const market = run?.banner.mode ? MARKET[run.banner.mode] : null
  const moduleById = new Map((modules.data?.modules ?? []).map((m) => [m.id, m]))

  return (
    <>
      <div className="page-head">
        <h1>Brain</h1>
        <button className="primary" disabled={runNow.isPending} onClick={() => runNow.mutate()}>
          {runNow.isPending ? 'Thinking…' : 'Run now'}
        </button>
      </div>
      <p className="muted" style={{ marginTop: '-0.4rem' }}>
        The new decision system, running beside the bot. It only suggests and records — it never places an order.
      </p>
      {runNow.isError && <ErrorBox error={runNow.error} />}

      {latest.isLoading && <Loading />}
      {latest.isError && !noRunYet && <ErrorBox error={latest.error} />}
      {noRunYet && <Empty label="The brain has not run yet. Press “Run now” to see what it thinks." />}

      {run && market && (
        <div className={`banner ${market.className}`} style={{ marginBottom: '1rem' }}>
          <strong>Market: {market.label}</strong> — {run.banner.headline}
          <div className="stat-sub" style={{ color: 'inherit' }}>
            {market.plain}
          </div>
        </div>
      )}

      {health.data && (
        <div className="grid brain-health" style={{ marginBottom: '1.25rem' }}>
          <div className="card">
            <div className="stat-sub">Last run</div>
            <strong>{health.data.last_run ? formatDateTime(health.data.last_run.started_at) : 'Never'}</strong>
            {health.data.last_run && (
              <div className="stat-sub">
                {health.data.last_run.status === 'done'
                  ? `Took ${(health.data.last_run.ms / 1000).toFixed(1)} s`
                  : `Failed: ${health.data.last_run.error}`}
              </div>
            )}
          </div>
          <div className="card">
            <div className="stat-sub">Price data</div>
            <strong>
              {health.data.data.fresh == null ? 'Not checked' : health.data.data.fresh ? 'Up to date' : 'Not reliable'}
            </strong>
            <div className="stat-sub">
              {health.data.data.fresh
                ? 'Every check passed.'
                : (health.data.data.issues[0] ?? '') +
                  (health.data.stale_count ? ` · ${health.data.stale_count} stocks affected` : '')}
            </div>
          </div>
          <div className="card">
            <div className="stat-sub">Failed runs, last 7 days</div>
            <strong>{health.data.failed_runs_7d}</strong>
            <div className="stat-sub">
              {health.data.failed_runs_7d ? 'See the run list below.' : 'None — every run finished.'}
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <h2>Ask about one stock</h2>
        <form
          className="brain-overrule"
          onSubmit={(e) => {
            e.preventDefault()
            if (whySymbol.trim()) why.mutate(whySymbol)
          }}
        >
          <input
            value={whySymbol}
            onChange={(e) => setWhySymbol(e.target.value)}
            placeholder="Stock symbol, e.g. RELIANCE"
            aria-label="Stock symbol"
          />
          <button className="primary" type="submit" disabled={why.isPending}>
            {why.isPending ? 'Thinking…' : 'Why?'}
          </button>
        </form>
        {why.isError && <ErrorBox error={why.error} />}
        {why.data && !why.data.decision && <Empty label="That stock was not found in the brain's list." />}
      </div>

      {run && (
        <div className="card" style={{ marginBottom: '1.25rem' }}>
          <div className="between">
            <h2>Today's ideas</h2>
            <span className="muted">{formatDateTime(run.started_at)}</span>
          </div>
          {active.length === 0 ? (
            <Empty label="Nothing to buy or watch right now." />
          ) : (
            <div className="table-wrap">
              <table>
                <tbody>
                  {active.map((d) => (
                    <DecisionRow key={d.id} d={d} onOpen={() => setOpen(d)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {quiet.length > 0 && (
            <button style={{ marginTop: '0.8rem' }} onClick={() => setShowQuiet((v) => !v)}>
              {showQuiet ? 'Hide' : 'Show'} {quiet.length} stocks with no action
            </button>
          )}
          {showQuiet && (
            <div className="table-wrap" style={{ marginTop: '0.6rem' }}>
              <table>
                <tbody>
                  {quiet.map((d) => (
                    <DecisionRow key={d.id} d={d} onOpen={() => setOpen(d)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {run && holdings.length > 0 && (
        <div className="card" style={{ marginBottom: '1.25rem' }}>
          <h2>Stocks you hold</h2>
          <div className="table-wrap">
            <table>
              <tbody>
                {holdings.map((d) => (
                  <DecisionRow key={d.id} d={d} onOpen={() => setOpen(d)} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {modules.data && (
        <div className="card" style={{ marginBottom: '1.25rem' }}>
          <h2>The eight thinking steps</h2>
          <p className="stat-sub">
            Each step is answered by an installed module, or by a simple built-in answer until one is built. “Trial”
            runs a module and records its answer without using it.
          </p>
          <div className="table-wrap">
            <table>
              <tbody>
                {modules.data.steps.map((s) => (
                  <tr key={s.step}>
                    <td>
                      <strong>{STEP_LABEL[s.step] ?? s.step}</strong>
                    </td>
                    <td>
                      {s.modules.length === 0 && <span className="muted">Simple built-in answer</span>}
                      {s.modules.map((id) => {
                        const m = moduleById.get(id)
                        return m ? (
                          <div key={id} className="between brain-module">
                            <span>
                              {m.id} · {m.name}
                            </span>
                            <ModuleSwitch m={m} onChange={(mode) => setMode.mutate({ id: m.id, mode })} />
                          </div>
                        ) : null
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {setMode.isError && <ErrorBox error={setMode.error} />}
        </div>
      )}

      {runs.data && runs.data.length > 0 && (
        <div className="card">
          <h2>Recent runs</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Market</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.run_id}>
                    <td>
                      {formatDateTime(r.started_at)}
                      <div className="stat-sub">
                        {r.kind === 'why' ? 'One stock' : r.kind === 'intraday' ? 'Holdings check' : 'Nightly'}
                        {!r.live && ' · replay'}
                      </div>
                    </td>
                    <td>{r.banner.mode ? MARKET[r.banner.mode].label : '—'}</td>
                    <td>
                      {r.status === 'failed' ? (
                        <span className="badge badge-off">Failed</span>
                      ) : (
                        Object.entries(r.counts)
                          .map(([w, n]) => `${n} ${w}`)
                          .join(' · ')
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {open && (
        <Modal onClose={() => setOpen(null)}>
          <DecisionDetail
            decision={open}
            trace={trace.data?.trace}
            onOverruled={() => {
              setOpen(null)
              refreshAll()
            }}
          />
        </Modal>
      )}
      {why.data?.decision && (
        <Modal onClose={() => why.reset()}>
          <DecisionDetail decision={why.data.decision} trace={why.data.trace} onOverruled={() => why.reset()} />
        </Modal>
      )}
    </>
  )
}
