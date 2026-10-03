import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { BrainProposal, BrainProposalStatus } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { useBrainStatus, useLearning, useProposals } from '../live'
import { currentBuyLevelProposal } from '../live-system'
import { BrainOff, Card, CheckItem, Tag } from '../ui'

const PROPOSAL_STATUS_LABEL: Record<BrainProposalStatus, string> = {
  open: 'Open',
  accepted: 'Accepted',
  dismissed: 'Rejected',
}

const PROPOSAL_STATUS_TONE: Record<BrainProposalStatus, 'blue' | 'green' | 'red'> = {
  open: 'blue',
  accepted: 'green',
  dismissed: 'red',
}

function ProposalRow({
  p,
  pending,
  onDecide,
}: {
  p: BrainProposal
  pending: boolean
  onDecide: (id: number, action: 'accept' | 'reject', note: string) => void
}) {
  const [note, setNote] = useState('')
  return (
    <tr>
      <td>
        <div className="tm-strong">{p.title}</div>
        <div className="tm-faint">{p.evidence}</div>
      </td>
      <td>
        <Tag tone={PROPOSAL_STATUS_TONE[p.status]}>{PROPOSAL_STATUS_LABEL[p.status]}</Tag>
        {p.status !== 'open' && (
          <div className="tm-faint">
            {p.decided_by ? `by ${p.decided_by}` : ''}
            {p.decided_at ? ` on ${formatDateTime(p.decided_at)}` : ''}
            {p.decided_note ? ` — “${p.decided_note}”` : ''}
          </div>
        )}
      </td>
      <td>
        {p.status === 'open' && (
          <div className="tm-flex" style={{ gap: '0.4rem', flexWrap: 'wrap' }}>
            <input
              className="tm-input"
              style={{ minWidth: 140 }}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Optional note"
              aria-label={`Note for ${p.title}`}
            />
            <button className="tm-btn" disabled={pending} onClick={() => onDecide(p.id, 'accept', note)}>
              Accept
            </button>
            <button className="tm-btn" disabled={pending} onClick={() => onDecide(p.id, 'reject', note)}>
              Reject
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}

export default function Learn() {
  const status = useBrainStatus()
  const queryClient = useQueryClient()
  const learning = useLearning()
  const proposals = useProposals()

  const decideProposal = useMutation({
    mutationFn: ({ id, action, note }: { id: number; action: 'accept' | 'reject'; note: string }) =>
      api.brainProposalDecide(id, action, note),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['brainLearning'] })
      void queryClient.invalidateQueries({ queryKey: ['brainProposals'] })
    },
  })
  const revertBuyLevel = useMutation({
    mutationFn: api.brainRevertBuyLevel,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['brainLearning'] })
      void queryClient.invalidateQueries({ queryKey: ['brainProposals'] })
    },
  })

  if (status === 'off') return <div className="tm-page"><BrainOff /></div>

  if (status === 'loading') {
    return (
      <div className="tm-page">
        <p className="tm-dim">Connecting to the brain…</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tm-page">
        <Card title="Could not reach the brain">
          <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  const data = learning.data
  const hasBreakdown = !!data && (data.by_band.length > 0 || data.by_word.length > 0 || data.by_week.length > 0)
  const buyLevelProposal = proposals.data ? currentBuyLevelProposal(proposals.data) : null

  return (
    <div className="tm-page tm-grid">
      <Card
        glow
        title="Learning From Results"
        sub="How well the brain's past ideas actually worked out, and any changes it wants to make. Nothing changes until you press Accept."
      >
        {learning.isLoading && <p className="tm-dim">Loading…</p>}
        {learning.isError && <p className="tm-dim">Could not load the learning report.</p>}
        {data && (
          <>
            {data.note && <p className="tm-note">{data.note}</p>}

            {data.by_band.length > 0 && (
              <>
                <div className="tm-strong" style={{ marginTop: '0.9rem' }}>
                  Model score (a ranking, not a chance)
                </div>
                <div className="tm-table-wrap">
                  <table className="tm-table">
                    <thead>
                      <tr>
                        <th>Model score</th>
                        <th className="tm-right">Ideas</th>
                        <th className="tm-right">The brain said</th>
                        <th className="tm-right">What happened</th>
                        <th className="tm-right">Average result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_band.map((b) => (
                        <tr key={b.band}>
                          <td>{b.band}</td>
                          <td className="tm-right tm-num">{b.n}</td>
                          <td className="tm-right tm-num">{(b.said * 100).toFixed(0)}%</td>
                          <td className="tm-right tm-num">{(b.hit * 100).toFixed(0)}%</td>
                          <td className="tm-right tm-num">
                            {b.avg_r >= 0 ? '+' : ''}
                            {b.avg_r.toFixed(2)} R
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {data.by_word.length > 0 && (
              <>
                <div className="tm-strong" style={{ marginTop: '0.9rem' }}>
                  By decision
                </div>
                <div className="tm-table-wrap">
                  <table className="tm-table">
                    <thead>
                      <tr>
                        <th>Decision</th>
                        <th className="tm-right">Ideas</th>
                        <th className="tm-right">What happened</th>
                        <th className="tm-right">Average result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_word.map((w) => (
                        <tr key={w.word}>
                          <td className="tm-strong">{w.word}</td>
                          <td className="tm-right tm-num">{w.n}</td>
                          <td className="tm-right tm-num">{(w.hit * 100).toFixed(0)}%</td>
                          <td className="tm-right tm-num">
                            {w.avg_r >= 0 ? '+' : ''}
                            {w.avg_r.toFixed(2)} R
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {data.by_week.length > 0 && (
              <>
                <div className="tm-strong" style={{ marginTop: '0.9rem' }}>
                  By week
                </div>
                <div className="tm-table-wrap">
                  <table className="tm-table">
                    <thead>
                      <tr>
                        <th>Week</th>
                        <th className="tm-right">Ideas</th>
                        <th className="tm-right">What happened</th>
                        <th className="tm-right">Average result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_week.map((w) => (
                        <tr key={w.week}>
                          <td>{w.week}</td>
                          <td className="tm-right tm-num">{w.n}</td>
                          <td className="tm-right tm-num">{(w.hit * 100).toFixed(0)}%</td>
                          <td className="tm-right tm-num">
                            {w.avg_r >= 0 ? '+' : ''}
                            {w.avg_r.toFixed(2)} R
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {hasBreakdown && <p className="tm-faint">(1 R = the 4% risked on each trade)</p>}

            {!hasBreakdown && (
              <p className="tm-dim">Not enough finished ideas yet to break results down.</p>
            )}

            {data.failures.length > 0 && (
              <>
                <div className="tm-strong" style={{ marginTop: '0.9rem' }}>
                  What tends to go wrong
                </div>
                {data.failures.map((f, i) => (
                  <CheckItem key={i} tone="warn">
                    {f}
                  </CheckItem>
                ))}
              </>
            )}

            {data.drift_lines.length > 0 ? (
              <>
                <div className="tm-strong" style={{ marginTop: '0.9rem' }}>
                  Has the market changed under the model?
                </div>
                {data.drift_lines.map((d, i) => (
                  <CheckItem key={i} tone="neutral">
                    {d}
                  </CheckItem>
                ))}
              </>
            ) : (
              data.drift_note && <p className="tm-dim">{data.drift_note}</p>
            )}
          </>
        )}
      </Card>

      <Card
        title="Proposals"
        sub="Changes the brain wants to make, based on the results above. Nothing changes until you press Accept."
      >
        <p className="tm-faint" style={{ marginBottom: '0.6rem' }}>
          Accepting a buy level changes what the brain suggests from its next nightly run; it does not change how the
          existing bot trades.
        </p>
        {buyLevelProposal && (
          <button className="tm-btn" disabled={revertBuyLevel.isPending} onClick={() => revertBuyLevel.mutate()}>
            Go back to the default buy level
          </button>
        )}
        {revertBuyLevel.isError && <p className="tm-dim">Could not revert the buy level. Try again shortly.</p>}
        {proposals.isLoading && <p className="tm-dim">Loading…</p>}
        {proposals.isError && <p className="tm-dim">Could not load proposals.</p>}
        {proposals.data && proposals.data.length === 0 && <p className="tm-dim">No proposals right now.</p>}
        {proposals.data && proposals.data.length > 0 && (
          <div className="tm-table-wrap" style={{ marginTop: '0.6rem' }}>
            <table className="tm-table">
              <tbody>
                {proposals.data.map((p) => (
                  <ProposalRow
                    key={p.id}
                    p={p}
                    pending={decideProposal.isPending}
                    onDecide={(id, action, note) => decideProposal.mutate({ id, action, note })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {decideProposal.isError && <p className="tm-dim">Could not record that decision. Try again shortly.</p>}
      </Card>
    </div>
  )
}
