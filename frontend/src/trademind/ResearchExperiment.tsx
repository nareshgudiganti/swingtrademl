// The research experiment on the 5- and 30-day horizons (design rev 3): the owner's hand-picked stocks, scored
// each evening from daily prices as if bought at the next open and sold after N trading days. Simulated only:
// no order, no money, nothing the brain or the 15-day trial uses. Owner only (the API refuses everyone else).
// It is never a trading strategy and never "validated": the backend's verdict is "Not proven" until the owner
// reviews it after the minimum sample.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { ExperimentOutcome, ExperimentSelection } from '../api/types'
import type { Horizon } from './horizons'
import { Card, Tag } from './ui'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-10-19" -> "19 Oct". No Date parsing, so no time-zone surprises. */
export function day(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [, m, d] = iso.slice(0, 10).split('-')
  return `${Number(d)} ${MONTHS[Number(m) - 1] ?? ''}`
}

export function pct(x: number | null | undefined, digits = 1): string {
  if (x == null) return '—'
  const v = x * 100
  return `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(digits)}%`
}

const STATE_LABEL: Record<ExperimentOutcome['state'], string> = {
  closed: 'Closed',
  open: 'Running',
  pending: 'Waiting to start',
  data_issue: 'Data issue',
  void: 'Could not be simulated',
}

const FLAG_TEXT: Record<string, string> = {
  missing_bar: 'a missing day of prices',
  big_gap: 'a one-day jump over 30%',
  corporate_action: 'a split or bonus in the window',
  holiday_calendar_missing: 'the NSE holiday list for that year is not out yet',
  price_above_notional: 'one share costs more than the amount per pick',
}

function whyNotScored(o: ExperimentOutcome): string {
  const reasons = Object.keys(o.data_flags ?? {})
    .filter((k) => k in FLAG_TEXT)
    .map((k) => FLAG_TEXT[k])
  return `Not scored: ${reasons.join(', ') || 'data problem'}`
}

/** Today's IST date and whether a pick for `entry` can still be changed (before 09:00 IST on that day). */
function canStillChange(entry: string | null, cutoff = '09:00'): boolean {
  if (!entry) return false
  const now = new Date()
  const ist = new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000)
  const today = `${ist.getFullYear()}-${String(ist.getMonth() + 1).padStart(2, '0')}-${String(ist.getDate()).padStart(2, '0')}`
  const hhmm = `${String(ist.getHours()).padStart(2, '0')}:${String(ist.getMinutes()).padStart(2, '0')}`
  return today < entry || (today === entry && hhmm < cutoff)
}

export function ResearchExperiment({ horizon: h }: { horizon: Horizon }) {
  const qc = useQueryClient()
  const report = useQuery({ queryKey: ['experiments', 'report'], queryFn: api.experimentsReport, retry: false })
  const outcomes = useQuery({ queryKey: ['experiments', 'outcomes'], queryFn: api.experimentsOutcomes, retry: false })
  const selections = useQuery({
    queryKey: ['experiments', 'selections'],
    queryFn: api.experimentsSelections,
    retry: false,
  })
  const [symbol, setSymbol] = useState('')
  const [note, setNote] = useState('')
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [fixing, setFixing] = useState<{ id: number; symbol: string } | null>(null)

  const refresh = () => qc.invalidateQueries({ queryKey: ['experiments'] })
  const explain = (s: ExperimentSelection) =>
    s.status === 'accepted'
      ? {
          ok: true,
          text: `Recorded ${s.symbol}. It starts at the open on ${day(s.entry_session)} and is scored after 5 and 30 trading days. You can change it until 09:00 IST that morning.`,
        }
      : { ok: false, text: `Not recorded: ${s.reject_reason ?? 'refused'}` }

  const add = useMutation({
    mutationFn: () => api.experimentAddPick({ symbol, intended_horizon: h.days, note: note || null }),
    onSuccess: (s) => {
      setMessage(explain(s))
      if (s.status === 'accepted') {
        setSymbol('')
        setNote('')
      }
      refresh()
    },
    onError: (e: Error) => setMessage({ ok: false, text: `Could not save: ${e.message}` }),
  })
  const correct = useMutation({
    mutationFn: (f: { id: number; symbol: string }) =>
      api.experimentCorrectPick(f.id, { symbol: f.symbol, intended_horizon: h.days }),
    onSuccess: (s) => {
      setMessage(explain(s))
      setFixing(null)
      refresh()
    },
    onError: (e: Error) => setMessage({ ok: false, text: `Could not change it: ${e.message}` }),
  })

  const r = report.data?.horizons.find((x) => x.horizon === h.days)
  const mine = (outcomes.data ?? []).filter((o) => o.horizon === h.days)
  const changeable = (selections.data ?? []).filter(
    (s) => s.status === 'accepted' && s.intended_horizon === h.days && canStillChange(s.entry_session),
  )
  const supersededIds = new Set((selections.data ?? []).filter((s) => s.status === 'accepted').map((s) => s.supersedes_id))
  const refused = (selections.data ?? []).filter(
    (s) => s.status === 'rejected' && (s.intended_horizon === h.days || s.intended_horizon == null),
  )

  return (
    <div className="tm-grid" data-testid="research-experiment" style={{ marginTop: '0.8rem' }}>
      <Card
        title={`Research experiment: ${h.title}`}
        sub="Your own picks, scored as if bought at the next open and sold after the window. Simulated: no order, no money. Not a trading strategy."
        action={<Tag tone="amber">{r?.label ?? 'Research, owner-selected, unproven'}</Tag>}
      >
        {report.isLoading && <p className="tm-dim">Loading the experiment…</p>}
        {report.isError && <p className="tm-dim">Could not load the experiment right now.</p>}
        {r && (
          <dl className="tm-kv">
            <dt>Verdict</dt>
            <dd>
              <strong>{r.verdict}</strong>
            </dd>
            <dt>Sample so far</dt>
            <dd>
              {r.independent_samples} of {r.minimum_needed} independent samples needed (picks started on different
              days; {r.non_overlapping} with no overlap)
            </dd>
            <dt>Period</dt>
            <dd>{r.period.from ? `${day(r.period.from)} – ${day(r.period.to)}` : 'No finished picks yet'}</dd>
            <dt>Average return after costs</dt>
            <dd>
              {pct(r.mean_net_return)} per pick ({pct(r.mean_net_return_per_day, 2)} per trading day held)
            </dd>
            <dt>Against NIFTY</dt>
            <dd>{pct(r.mean_excess_vs_nifty)}</dd>
            <dt>Against the average stock</dt>
            <dd>{pct(r.mean_excess_vs_universe)}</dd>
            <dt>Likely range of the average</dt>
            <dd>
              {r.net_return_range_90
                ? `${pct(r.net_return_range_90[0])} to ${pct(r.net_return_range_90[1])} (90%)`
                : 'Needs at least two finished picks'}
            </dd>
            <dt>Picks that made money</dt>
            <dd>{r.win_rate == null ? '—' : `${Math.round(r.win_rate * 100)}% (not a measure of skill on its own)`}</dd>
            <dt>Not yet finished</dt>
            <dd>
              {r.open} running · {r.pending} waiting to start · {r.data_issues} with a data issue
            </dd>
          </dl>
        )}
        {report.data && (
          <details className="tm-note" style={{ marginTop: '0.5rem' }}>
            <summary>What these numbers do and do not show</summary>
            <p>{report.data.owner_selected_note}</p>
            <ul>
              {report.data.limits.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </details>
        )}
      </Card>

      <Card title="Add a pick" sub="Saved before 09:00 IST on a trading day: starts at that day's open. Otherwise: the next trading day's open.">
        <form
          data-testid="experiment-form"
          className="tm-toolbar"
          onSubmit={(e) => {
            e.preventDefault()
            if (symbol.trim()) add.mutate()
          }}
        >
          <input
            className="tm-input"
            name="symbol"
            placeholder="Stock symbol, e.g. TCS"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            aria-label="Stock symbol"
            maxLength={64}
          />
          <input
            className="tm-input"
            name="note"
            placeholder="Why (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="Why you picked it (optional)"
            maxLength={500}
          />
          <button type="submit" className="tm-btn" disabled={!symbol.trim() || add.isPending}>
            {add.isPending ? 'Saving…' : `Add to the ${h.title} experiment`}
          </button>
        </form>
        <p className="tm-note">Every pick is kept with its time and cannot be deleted. One pick per stock at a time.</p>
        {message && (
          <p className={message.ok ? 'tm-pos' : 'tm-neg'} role="status">
            {message.text}
          </p>
        )}
        {changeable.length > 0 && (
          <div style={{ marginTop: '0.5rem' }}>
            <div className="tm-strong">Can still be changed (until 09:00 IST on the start day)</div>
            {changeable
              .filter((s) => !supersededIds.has(s.id))
              .map((s) => (
                <div key={s.id} className="tm-toolbar" style={{ marginTop: '0.3rem' }}>
                  <span>
                    {s.symbol} · starts {day(s.entry_session)}
                  </span>
                  {fixing?.id === s.id ? (
                    <>
                      <input
                        className="tm-input"
                        value={fixing.symbol}
                        onChange={(e) => setFixing({ id: s.id, symbol: e.target.value.toUpperCase() })}
                        aria-label={`New symbol instead of ${s.symbol}`}
                      />
                      <button
                        type="button"
                        className="tm-btn"
                        disabled={!fixing.symbol.trim() || correct.isPending}
                        onClick={() => correct.mutate(fixing)}
                      >
                        Save change
                      </button>
                      <button type="button" className="tm-btn" onClick={() => setFixing(null)}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button type="button" className="tm-btn" onClick={() => setFixing({ id: s.id, symbol: s.symbol })}>
                      Change
                    </button>
                  )}
                </div>
              ))}
          </div>
        )}
      </Card>

      <Card title={`Your ${h.title} picks`} sub="Returns are after costs and slippage. NIFTY and the average stock are measured over the same days.">
        {outcomes.isLoading && <p className="tm-dim">Loading picks…</p>}
        {outcomes.isError && <p className="tm-dim">Could not load the picks right now.</p>}
        {outcomes.data && mine.length === 0 && (
          <p className="tm-dim">No picks yet. Picks are scored every weekday evening after the market closes.</p>
        )}
        {mine.length > 0 && (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th>Started</th>
                  <th>State</th>
                  <th className="tm-right">Return after costs</th>
                  <th className="tm-right">vs NIFTY</th>
                  <th className="tm-right">vs average stock</th>
                </tr>
              </thead>
              <tbody>
                {mine.map((o) => (
                  <tr key={`${o.selection_id}-${o.horizon}`}>
                    <td className="tm-strong">{o.symbol}</td>
                    <td>{day(o.entry_session)}</td>
                    <td>
                      {STATE_LABEL[o.state]}
                      {o.state === 'closed' && o.exit_session ? ` ${day(o.exit_session)}` : ''}
                      {o.state === 'open' && o.mark_session ? ` (as of ${day(o.mark_session)})` : ''}
                    </td>
                    {o.state === 'data_issue' || o.state === 'void' || o.state === 'pending' ? (
                      <td className="tm-dim" colSpan={3}>
                        {o.state === 'pending' && !o.data_flags?.holiday_calendar_missing
                          ? 'Not started yet'
                          : whyNotScored(o)}
                      </td>
                    ) : (
                      <>
                        <td className="tm-right tm-num">{pct(o.net_return)}</td>
                        <td className="tm-right tm-num">{pct(o.excess_vs_nifty)}</td>
                        <td className="tm-right tm-num">{pct(o.excess_vs_universe)}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {refused.length > 0 && (
          <details className="tm-note" style={{ marginTop: '0.5rem' }}>
            <summary>Refused picks ({refused.length})</summary>
            <ul>
              {refused.map((s) => (
                <li key={s.id}>
                  {s.symbol} ({day(s.submitted_at.slice(0, 10))}): {s.reject_reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Card>
    </div>
  )
}
