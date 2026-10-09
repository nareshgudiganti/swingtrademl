// Go-live: the brain's trading controls, in TradeMind's own look. Same
// behaviour and safety rules as the old components/BrainGoLive.tsx — practice
// first, the owner's OK second, automatic last — in plain words.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { BrainApproval, BrainApprovalStatus, BrainCompareSummary, BrainStageName } from '../../api/types'
import { formatCurrency, formatDateTime, formatSignedPercent } from '../../lib/format'
import { Confirm } from '../Confirm'
import { BrainGate, Card, PageHead, Tag } from '../ui'

const STAGE_ORDER: BrainStageName[] = ['shadow', 'approval', 'auto']
const STAGE_TITLE: Record<BrainStageName, string> = {
  shadow: 'Practice only',
  approval: 'Your OK needed',
  auto: 'Automatic',
}

const STATUS_TONE: Record<BrainApprovalStatus, 'amber' | 'blue' | 'green' | 'red' | 'violet'> = {
  pending: 'amber',
  waiting: 'blue',
  approved: 'green',
  rejected: 'red',
  expired: 'violet',
}

function pct(value: number | null): string {
  return value === null ? 'n/a' : `${(value * 100).toFixed(0)}%`
}

function avg(value: number | null): string {
  return value === null ? 'n/a' : formatSignedPercent(value, 1)
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

export default function GoLive() {
  return (
    <BrainGate allowNoRun what="the trading controls">
      <div className="tm-page tm-grid">
        <PageHead
          title="Go-live"
          sub="Decide whether the brain only practises, asks for your OK before buying, or buys by itself."
        />
        <StageCard />
        <ApprovalsCard />
        <CompareCard />
      </div>
    </BrainGate>
  )
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

function CompareCard() {
  const compare = useQuery({ queryKey: ['brainCompare'], queryFn: api.brainCompare })
  const data = compare.data
  return (
    <Card
      title="Brain vs version 1"
      sub="The brain runs as a practice strategy next to version 1. Both are scored the same way: did the price reach the target before the stop? Only days when the brain ran are compared."
    >
      {compare.isLoading && <p className="tm-dim">Loading…</p>}
      {compare.isError && <p className="tm-neg">Could not load the comparison: {errText(compare.error)}</p>}
      {data && (
        <div className="tm-grid">
          <div className="tm-note">{data.note}</div>
          <p className="tm-dim tm-gl-p">
            {Math.min(data.brain_finished, data.needed)} of {data.needed} brain ideas have finished. {data.needed} are
            needed before its ideas can be bought, and even then only with your OK.
          </p>
          {data.strategies.length > 0 && (
            <div className="tm-table-wrap">
              <table className="tm-table">
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
                      <td className="tm-strong">{s.is_brain ? `${s.name} (brain)` : s.name}</td>
                      <SummaryCells s={s} />
                    </tr>
                  ))}
                  <tr>
                    <td className="tm-dim">All of version 1</td>
                    <SummaryCells s={data.version1} />
                  </tr>
                </tbody>
              </table>
            </div>
          )}
          {data.by_week.length > 0 && (
            <>
              <div className="tm-strong">By week</div>
              <div className="tm-table-wrap">
                <table className="tm-table">
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
        </div>
      )}
    </Card>
  )
}

function StageCard() {
  const queryClient = useQueryClient()
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage })
  const [picked, setPicked] = useState<BrainStageName | null>(null)
  const [asking, setAsking] = useState(false)
  const s = stage.data
  const allowed = (name: BrainStageName): boolean =>
    !!s && name !== s.stage && (name === 'shadow' || (s.ready && (name === 'approval' || s.stage === 'approval')))
  const target: BrainStageName = picked && allowed(picked) ? picked : STAGE_ORDER.find(allowed) ?? 'shadow'
  const change = useMutation({
    mutationFn: (reason: string) => api.brainSetStage(target, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['brainStage'] })
      void queryClient.invalidateQueries({ queryKey: ['brainApprovals'] })
      void queryClient.invalidateQueries({ queryKey: ['brainCompare'] })
    },
  })

  return (
    <Card title="Trading stage">
      {stage.isLoading && <p className="tm-dim">Loading…</p>}
      {stage.isError && <p className="tm-neg">Could not load the stage: {errText(stage.error)}</p>}
      {s && (
        <div className="tm-grid">
          <div>
            <div className="tm-strong">Now: {STAGE_TITLE[s.stage]}</div>
            <div className="tm-dim tm-gl-p">{s.plain}</div>
          </div>
          <p className="tm-dim tm-gl-p">
            {Math.min(s.finished, s.needed)} of {s.needed} brain ideas have finished.{' '}
            {s.ready
              ? 'That is enough evidence to move on, if you choose to.'
              : `The brain stays in practice until ${s.needed} have finished.`}{' '}
            Going back to practice is always allowed and takes effect at once.
          </p>
          {s.finished_blocked !== undefined && (
            <p className="tm-dim tm-gl-p">
              {s.finished_blocked} more finished {s.finished_blocked === 1 ? 'idea was' : 'ideas were'} stopped by the
              safety limits (for example, too much money already invested while the market is stressed). They are
              scored for practice but do not count toward the {s.needed}.
            </p>
          )}
          <p className="tm-dim tm-gl-p">
            Going back to practice stops new buying. Ideas waiting for your OK, and ideas you approved that are not
            placed yet, are cancelled and nothing new is bought. Shares the brain already bought are kept: the usual
            stop-loss, target and time limit keep protecting them, or you can sell them yourself on the Positions page.
          </p>
          <p className="tm-dim tm-gl-p">
            Moving to Automatic is your own call. There is no extra test beyond the {s.needed} finished ideas, and you
            can only reach it from “Your OK needed”.
          </p>
          <div className="tm-gl-row">
            <div className="tm-seg" role="group" aria-label="New stage">
              {STAGE_ORDER.map((name) => (
                <button
                  key={name}
                  className={name === target ? 'active' : ''}
                  disabled={!allowed(name)}
                  onClick={() => setPicked(name)}
                >
                  {STAGE_TITLE[name]}
                </button>
              ))}
            </div>
            <button className="tm-btn" disabled={!allowed(target)} onClick={() => setAsking(true)}>
              Change stage
            </button>
          </div>
          {s.history.length > 0 && (
            <div className="tm-grid" style={{ gap: '0.4rem' }}>
              <div className="tm-strong">Past changes</div>
              {s.history.map((h) => (
                <div key={h.changed_at + h.stage} className="tm-gl-item">
                  <div>
                    {STAGE_TITLE[h.previous_stage]} → {STAGE_TITLE[h.stage]}
                  </div>
                  <div className="tm-faint">
                    {formatDateTime(h.changed_at)} · by {h.changed_by}
                  </div>
                  {h.reason && <div className="tm-dim">“{h.reason}”</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {asking && s && (
        <Confirm
          title={`Move to “${STAGE_TITLE[target]}”?`}
          confirmLabel="Change stage"
          danger={target === 'auto'}
          reason={{ label: 'Why are you changing it?', placeholder: 'e.g. 30 ideas look good' }}
          onConfirm={(reason) => change.mutateAsync(reason)}
          onClose={() => setAsking(false)}
        >
          {target === 'shadow' && (
            <>
              New buying stops now. Ideas waiting for your OK, and approved ideas not placed yet, are cancelled. Shares
              already bought are kept and stay protected.
            </>
          )}
          {target === 'approval' && <>The brain will put each idea here and wait for your OK before anything is bought.</>}
          {target === 'auto' && (
            <>
              The brain will buy its ideas by itself, without asking you each time. Only do this if you are happy with
              how its practice ideas turned out.
            </>
          )}
        </Confirm>
      )}
    </Card>
  )
}

function ApprovalItem({
  a,
  canDecide,
  onApprove,
  onReject,
}: {
  a: BrainApproval
  canDecide: boolean
  onApprove: (a: BrainApproval) => void
  onReject: (a: BrainApproval) => void
}) {
  return (
    <div className="tm-gl-item">
      <div className="tm-between">
        <span className="tm-strong">{a.symbol}</span>
        <Tag tone={STATUS_TONE[a.status]}>{a.status_plain}</Tag>
      </div>
      <div className="tm-dim">{a.reason}</div>
      <div>
        {formatCurrency(a.price)}
        <span className="tm-faint">
          {a.stop_loss !== null && ` · Stop ${formatCurrency(a.stop_loss)}`}
          {a.take_profit !== null && ` · Target ${formatCurrency(a.take_profit)}`}
          {a.suggested_qty !== null && ` · about ${a.suggested_qty} shares`}
        </span>
      </div>
      {a.valid_until && <div className="tm-faint">Open until {formatDateTime(a.valid_until)}</div>}
      {a.decided_note && <div className="tm-faint">“{a.decided_note}”</div>}
      {a.result_note && <div className="tm-faint">{a.result_note}</div>}
      {a.status === 'pending' && (
        <div className="tm-gl-actions" style={{ marginTop: '0.3rem' }}>
          {canDecide && (
            <button className="tm-btn" onClick={() => onApprove(a)}>
              Approve
            </button>
          )}
          <button className="tm-btn tm-btn-ghost" onClick={() => onReject(a)}>
            Reject
          </button>
        </div>
      )}
    </div>
  )
}

function ApprovalsCard() {
  const queryClient = useQueryClient()
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage })
  const list = useQuery({ queryKey: ['brainApprovals'], queryFn: api.brainApprovals })
  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const moneyKind = status.data
    ? status.data.trading_mode === 'live'
      ? 'REAL money'
      : 'practice money (paper trading)'
    : null
  const [dialog, setDialog] = useState<{ kind: 'approve' | 'reject'; a: BrainApproval } | null>(null)
  const canDecide = !!stage.data && stage.data.stage !== 'shadow'
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['brainApprovals'] })
    void queryClient.invalidateQueries({ queryKey: ['brainCompare'] })
    for (const key of ['positions', 'status', 'summary']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
  }
  const approve = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) => api.brainApprove(id, note),
    onSettled: refresh,
  })
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => api.brainReject(id, reason),
    onSettled: refresh,
  })

  return (
    <Card
      title="Waiting for your OK"
      sub="In the “Your OK needed” stage, each brain idea waits here. Approve checks again that the brain still likes the idea and that the safety rules allow it — only then is it bought. An idea stays open until the next trading day’s market closes. If you approve while the market is closed, nothing is ordered yet: it shows as “Approved — will be placed when the market opens”, and the checks run once more at the open."
    >
      <div className="tm-grid">
        {stage.data && stage.data.stage === 'shadow' && (
          <div className="tm-note">
            The brain is in practice mode, so nothing can be approved or bought. You can still reject an idea.
          </div>
        )}
        {list.isLoading && <p className="tm-dim">Loading…</p>}
        {list.isError && <p className="tm-neg">Could not load the list: {errText(list.error)}</p>}
        {list.data && list.data.length === 0 && <p className="tm-dim">Nothing is waiting.</p>}
        {list.data?.map((a) => (
          <ApprovalItem
            key={a.id}
            a={a}
            canDecide={canDecide}
            onApprove={(x) => setDialog({ kind: 'approve', a: x })}
            onReject={(x) => setDialog({ kind: 'reject', a: x })}
          />
        ))}
      </div>
      {dialog?.kind === 'approve' && (
        <Confirm
          title={`Approve ${dialog.a.symbol}?`}
          confirmLabel="Approve"
          reason={{ label: 'Note (optional)', required: false }}
          onConfirm={(note) => approve.mutateAsync({ id: dialog.a.id, note })}
          onClose={() => setDialog(null)}
        >
          The brain and the safety rules check the idea again first. Only if it still passes is it bought
          {dialog.a.suggested_qty !== null ? ` (about ${dialog.a.suggested_qty} shares)` : ''}. If the market is closed,
          it is placed when the market opens.{' '}
          {moneyKind ? `This uses ${moneyKind}.` : 'Could not check whether this is practice or real money.'}
        </Confirm>
      )}
      {dialog?.kind === 'reject' && (
        <Confirm
          title={`Reject ${dialog.a.symbol}?`}
          confirmLabel="Reject"
          danger
          reason={{ label: 'Why are you rejecting it?', placeholder: 'A short reason' }}
          onConfirm={(reason) => reject.mutateAsync({ id: dialog.a.id, reason })}
          onClose={() => setDialog(null)}
        >
          Nothing will be bought for this idea.
        </Confirm>
      )}
    </Card>
  )
}
