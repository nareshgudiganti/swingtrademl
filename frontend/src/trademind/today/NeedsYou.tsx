// oa5: Today's "Needs you" section. Three kinds of thing wait on a person:
//  - holdings the brain flagged (the `holdings` slot; everyone — see HoldingsNeedsYou.tsx),
//  - ideas waiting for the owner's OK (M18 approval stage; owner only, decided on Go-live),
//  - learning proposals waiting for a decision (owner only, decided on Learn).
// Display only: nothing is approved, rejected or accepted here; each row links to the page that does it.
// The approvals and proposals answers are owner-only on the server, so they are not asked for anyone else.

import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainApproval, BrainProposal } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { withoutScorePercent } from '../scoreText'
import { useProposals } from '../live'
import { Card, Tag, inr } from '../ui'

/** A proposal title with any model score written without its % sign ("Raise the buy level to 65"). */
export function proposalTitle(title: string): string {
  return withoutScorePercent(title) // the one helper in scoreText also covers "buy level to 65%"
}

/** What is waiting: approvals still pending, open proposals that can be decided, and sealed ones that cannot yet. */
export function waitingItems(approvals: BrainApproval[] | undefined, proposals: BrainProposal[] | undefined) {
  const open = (proposals ?? []).filter((p) => p.status === 'open')
  return {
    approvals: (approvals ?? []).filter((a) => a.status === 'pending'),
    proposals: open.filter((p) => !p.sealed),
    sealed: open.filter((p) => p.sealed).length,
  }
}

export function NeedsYou({ owner, holdings }: { owner: boolean; holdings: ReactNode }) {
  return (
    <section className={`tm-grid ${owner ? 'tm-cols-2' : ''}`} data-testid="needs-you" aria-label="Needs you">
      {holdings}
      {owner && <WaitingForYou />}
    </section>
  )
}

function WaitingForYou() {
  const approvals = useQuery({ queryKey: ['brainApprovals'], queryFn: api.brainApprovals, retry: false })
  const proposals = useProposals()
  const w = waitingItems(approvals.data, proposals.data)

  return (
    <Card title="Waiting for your decision" sub="You decide on Go-live and Learn; nothing is decided here">
      <div data-feature="approvals-waiting">
        <div className="tm-card-sub" style={{ margin: '0 0 0.3rem' }}>
          Ideas waiting for your OK
        </div>
        {approvals.isLoading ? (
          <p className="tm-dim">Loading…</p>
        ) : approvals.isError && !approvals.data ? (
          <p className="tm-dim">Could not load the ideas waiting for your OK.</p>
        ) : w.approvals.length === 0 ? (
          <p className="tm-dim">No idea is waiting for your OK.</p>
        ) : (
          <div className="tm-rows">
            {w.approvals.map((a) => (
              <Link className="tm-row tm-clickable" key={a.id} to="/trademind/golive" data-approval={a.symbol}>
                <span style={{ display: 'grid', gap: '0.1rem' }}>
                  <span className="tm-strong">{a.symbol}</span>
                  <span className="tm-dim">
                    {`Paper buy at about ₹${inr(a.price)}`}
                    {a.valid_until ? `, open until ${formatDateTime(a.valid_until)}` : ''}
                  </span>
                </span>
                <Tag tone="amber">Decide on Go-live</Tag>
              </Link>
            ))}
          </div>
        )}
      </div>

      <div data-feature="proposals-waiting" style={{ marginTop: '0.8rem' }}>
        <div className="tm-card-sub" style={{ margin: '0 0 0.3rem' }}>
          Learning proposals
        </div>
        {proposals.isLoading ? (
          <p className="tm-dim">Loading…</p>
        ) : proposals.isError && !proposals.data ? (
          <p className="tm-dim">Could not load the learning proposals.</p>
        ) : (
          <>
            {w.proposals.length === 0 && w.sealed === 0 && <p className="tm-dim">No proposal is waiting for a decision.</p>}
            {w.proposals.length > 0 && (
              <div className="tm-rows">
                {w.proposals.map((p) => (
                  <Link className="tm-row tm-clickable" key={p.id} to="/trademind/learn" data-proposal={p.id}>
                    <span className="tm-strong">{proposalTitle(p.title)}</span>
                    <Tag tone="amber">Decide on Learn</Tag>
                  </Link>
                ))}
              </div>
            )}
            {w.sealed > 0 && (
              <p className="tm-dim" data-testid="sealed-proposals">
                {w.sealed === 1 ? '1 proposal is' : `${w.sealed} proposals are`} sealed until the blind trial ends, so{' '}
                {w.sealed === 1 ? 'it cannot' : 'they cannot'} be decided yet.
              </p>
            )}
          </>
        )}
      </div>
    </Card>
  )
}
