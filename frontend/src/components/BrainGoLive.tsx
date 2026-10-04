import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { BrainApproval, BrainCompareSummary, BrainStageName } from '../api/types'
import { formatCurrency, formatDateTime, formatSignedPercent } from '../lib/format'
import { Empty, ErrorBox, Loading } from './Loading'

/* Brain go-live (build book M18): the brain as a practice strategy next to
 * version 1, scored the same way. Plain words only. */

function pct(value: number | null): string {
  return value === null ? 'n/a' : `${(value * 100).toFixed(0)}%`
}

function avg(value: number | null): string {
  return value === null ? 'n/a' : formatSignedPercent(value, 1)
}

function SummaryCells({ s }: { s: BrainCompareSummary }) {
  return (
    <>
      <td>{s.ideas}</td>
      <td>{s.finished}</td>
      <td>{pct(s.hit_rate)}</td>
      <td>{pct(s.stopped)}</td>
      <td>{avg(s.avg_outcome_pct)}</td>
    </>
  )
}

export function BrainCompareCard() {
  const compare = useQuery({ queryKey: ['brainCompare'], queryFn: api.brainCompare })
  const data = compare.data
  return (
    <div className="card" style={{ marginBottom: '1.25rem' }}>
      <h2>Brain vs version 1</h2>
      <p className="stat-sub">
        The brain runs as a practice strategy next to version 1. Both are scored the same way: did the price reach
        the target before the stop? Only days when the brain ran are compared.
      </p>
      {compare.isLoading && <Loading />}
      {compare.isError && <ErrorBox error={compare.error} />}
      {data && (
        <>
          <div className="banner banner-info" style={{ margin: '0.6rem 0' }}>
            {data.note}
          </div>
          <p className="stat-sub">
            {Math.min(data.brain_finished, data.needed)} of {data.needed} brain ideas have finished. {data.needed} are
            needed before its ideas can be bought, and even then only with your OK.
          </p>
          {data.strategies.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Ideas</th>
                    <th>Finished</th>
                    <th>Reached the target</th>
                    <th>Hit the stop</th>
                    <th>Average result</th>
                  </tr>
                </thead>
                <tbody>
                  {data.strategies.map((s) => (
                    <tr key={s.name}>
                      <td>{s.is_brain ? <strong>{s.name} (brain)</strong> : s.name}</td>
                      <SummaryCells s={s} />
                    </tr>
                  ))}
                  <tr>
                    <td>
                      <em>All of version 1</em>
                    </td>
                    <SummaryCells s={data.version1} />
                  </tr>
                </tbody>
              </table>
            </div>
          )}
          {data.by_week.length > 0 && (
            <>
              <h3>By week</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Week</th>
                      <th>Brain: finished</th>
                      <th>Brain: reached the target</th>
                      <th>Brain: average</th>
                      <th>Version 1: finished</th>
                      <th>Version 1: reached the target</th>
                      <th>Version 1: average</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_week.map((w) => (
                      <tr key={w.week}>
                        <td>{w.week}</td>
                        <td>{w.brain.finished}</td>
                        <td>{pct(w.brain.hit_rate)}</td>
                        <td>{avg(w.brain.avg_outcome_pct)}</td>
                        <td>{w.version1.finished}</td>
                        <td>{pct(w.version1.hit_rate)}</td>
                        <td>{avg(w.version1.avg_outcome_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}

const STAGE_TITLE: Record<BrainStageName, string> = {
  shadow: 'Practice (shadow)',
  approval: 'Your OK needed',
  auto: 'Automatic',
}

export function BrainStageCard() {
  const queryClient = useQueryClient()
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage })
  const [target, setTarget] = useState<BrainStageName>('shadow')
  const [reason, setReason] = useState('')
  const change = useMutation({
    mutationFn: () => api.brainSetStage(target, reason),
    onSuccess: () => {
      setReason('')
      void queryClient.invalidateQueries({ queryKey: ['brainStage'] })
      void queryClient.invalidateQueries({ queryKey: ['brainApprovals'] })
    },
  })
  const s = stage.data
  const allowed = (name: BrainStageName): boolean =>
    !!s && name !== s.stage && (name === 'shadow' || (s.ready && (name === 'approval' || s.stage === 'approval')))
  return (
    <div className="card" style={{ marginBottom: '1.25rem' }}>
      <h2>Trading stage</h2>
      {stage.isLoading && <Loading />}
      {stage.isError && <ErrorBox error={stage.error} />}
      {s && (
        <>
          <p>
            <strong>Now: {STAGE_TITLE[s.stage]}</strong> — {s.plain}
          </p>
          <p className="stat-sub">
            {Math.min(s.finished, s.needed)} of {s.needed} brain ideas have finished.{' '}
            {s.ready
              ? 'That is enough evidence to move on, if you choose to.'
              : `The brain stays in practice until ${s.needed} have finished.`}{' '}
            Going back to practice is always allowed and takes effect at once.
          </p>
          <p className="stat-sub">
            Going back to practice stops new buying only. Shares the brain already bought are not sold: the usual
            stop-loss, target and time limit keep protecting them, or you can sell them yourself on the Positions
            page. Ideas still waiting for your OK expire.
          </p>
          <p className="stat-sub">
            Moving to Automatic is your own call. There is no extra test beyond the {s.needed} finished ideas, and you
            can only reach it from “Your OK needed”.
          </p>
          <div className="brain-overrule">
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value as BrainStageName)}
              aria-label="New stage"
            >
              {(['shadow', 'approval', 'auto'] as BrainStageName[]).map((name) => (
                <option key={name} value={name} disabled={!allowed(name)}>
                  {STAGE_TITLE[name]}
                </option>
              ))}
            </select>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why? e.g. 30 ideas look good"
              aria-label="Reason for the change"
            />
            <button
              className="primary"
              disabled={!allowed(target) || !reason.trim() || change.isPending}
              onClick={() => change.mutate()}
            >
              {change.isPending ? 'Saving…' : 'Change stage'}
            </button>
          </div>
          {change.isError && <ErrorBox error={change.error} />}
          {s.history.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Change</th>
                    <th>By</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {s.history.map((h) => (
                    <tr key={h.changed_at + h.stage}>
                      <td>{formatDateTime(h.changed_at)}</td>
                      <td>
                        {STAGE_TITLE[h.previous_stage]} → {STAGE_TITLE[h.stage]}
                      </td>
                      <td>{h.changed_by}</td>
                      <td>{h.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ApprovalRow({ a, canDecide, busy, onApprove, onReject }: {
  a: BrainApproval
  canDecide: boolean
  busy: boolean
  onApprove: (id: number, note: string) => void
  onReject: (id: number, reason: string) => void
}) {
  const [text, setText] = useState('')
  return (
    <tr>
      <td>
        <strong>{a.symbol}</strong>
        <div className="stat-sub">{a.reason}</div>
      </td>
      <td>
        {formatCurrency(a.price)}
        <div className="stat-sub">
          {a.stop_loss !== null && `Stop ${formatCurrency(a.stop_loss)}`}
          {a.take_profit !== null && ` · Target ${formatCurrency(a.take_profit)}`}
          {a.suggested_qty !== null && ` · about ${a.suggested_qty} shares`}
        </div>
      </td>
      <td>
        {a.status_plain}
        {a.decided_note && <div className="stat-sub">“{a.decided_note}”</div>}
        {a.result_note && <div className="stat-sub">{a.result_note}</div>}
      </td>
      <td>
        {a.status === 'pending' && (
          <div className="brain-overrule">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={canDecide ? 'Note (needed to reject)' : 'Why? (needed to reject)'}
              aria-label={`Note for ${a.symbol}`}
            />
            {canDecide && (
              <button className="primary" disabled={busy} onClick={() => onApprove(a.id, text)}>
                Approve
              </button>
            )}
            <button disabled={busy || !text.trim()} onClick={() => onReject(a.id, text)}>
              Reject
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}

export function BrainApprovalsCard() {
  const queryClient = useQueryClient()
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage })
  const list = useQuery({ queryKey: ['brainApprovals'], queryFn: api.brainApprovals })
  const canDecide = !!stage.data && stage.data.stage !== 'shadow'
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['brainApprovals'] })
    void queryClient.invalidateQueries({ queryKey: ['brainCompare'] })
  }
  const approve = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) => api.brainApprove(id, note),
    onSuccess: refresh,
    onError: refresh,
  })
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => api.brainReject(id, reason),
    onSuccess: refresh,
  })
  return (
    <div className="card" id="approvals" style={{ marginBottom: '1.25rem' }}>
      <h2>Waiting for your OK</h2>
      <p className="stat-sub">
        In the “Your OK needed” stage, each brain idea waits here. Approve checks again that the brain still likes the
        idea and that the safety rules allow it — only then is it bought. An idea stays open until the next trading
        day’s market closes. If you approve while the market is closed, nothing is ordered yet: it shows as
        “Approved — will be placed when the market opens”, and the checks run once more at the open.
      </p>
      {stage.data && stage.data.stage === 'shadow' && (
        <p className="stat-sub">
          The brain is in practice mode, so nothing can be approved or bought. You can still reject an idea.
        </p>
      )}
      {list.isLoading && <Loading />}
      {list.isError && <ErrorBox error={list.error} />}
      {list.data && list.data.length === 0 && <Empty label="Nothing is waiting." />}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th>
                <th>Price</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((a) => (
                <ApprovalRow
                  key={a.id}
                  a={a}
                  canDecide={canDecide}
                  busy={approve.isPending || reject.isPending}
                  onApprove={(id, note) => approve.mutate({ id, note })}
                  onReject={(id, reason) => reject.mutate({ id, reason })}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {approve.isError && <ErrorBox error={approve.error} />}
      {reject.isError && <ErrorBox error={reject.error} />}
    </div>
  )
}
