// Learning proposals made during the blind trial come back sealed from the server (services/trial_seal.py):
// title, evidence and change hidden. They cannot be judged blind, so the Learn page shows them without
// Accept / Reject, with a plain note instead.
import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { BrainProposal } from '../api/types'
import { SEALED_PROPOSAL_NOTE, currentBuyLevelProposal } from './live-system'
import { ProposalRow } from './pages/Learn'

const base: BrainProposal = {
  id: 1,
  kind: 'buy_level',
  title: 'Raise the buy level to 70%',
  evidence: 'Among 40 past ideas scored 70% or more, the average was +0.40 R.',
  change: { buy_level: 0.7 },
  status: 'open',
  created_at: '2026-10-09T14:30:00Z',
  decided_by: null,
  decided_at: null,
  decided_note: null,
  sealed: false,
}

const sealed: BrainProposal = {
  ...base,
  id: 2,
  title: "A learning proposal was made (details sealed until the trial's evaluation).",
  evidence: "Sealed until the trial's evaluation (blind test): counts only.",
  change: {},
  created_at: '2026-10-20T14:30:00Z',
  sealed: true,
  evidence_sealed: true,
}

function row(p: BrainProposal): string {
  return renderToString(
    <table>
      <tbody>
        <ProposalRow p={p} pending={false} onDecide={() => {}} />
      </tbody>
    </table>,
  )
}

describe('ProposalRow', () => {
  it('lets the owner accept or reject a proposal made before the trial', () => {
    const html = row(base)
    expect(html).toContain('Raise the buy level to 70%')
    expect(html).toContain('Accept')
    expect(html).toContain('Reject')
    expect(html).not.toContain(SEALED_PROPOSAL_NOTE)
  })

  it('shows a sealed proposal without Accept / Reject', () => {
    const html = row(sealed)
    expect(html).toContain(SEALED_PROPOSAL_NOTE)
    expect(html).toContain('details sealed')
    expect(html).not.toContain('Accept')
    expect(html).not.toContain('Reject')
    expect(html).not.toContain('<button')
  })
})

describe('currentBuyLevelProposal', () => {
  it('still offers the way back when the buy level in force came from a sealed proposal', () => {
    const accepted = { ...sealed, status: 'accepted' as const, decided_at: '2026-10-21T10:00:00Z' }
    expect(currentBuyLevelProposal([accepted])).toBe(accepted)
  })

  it('reads the owner revert (never sealed) as back to default', () => {
    const revert = {
      ...base,
      id: 3,
      title: 'Go back to the default buy level',
      change: { buy_level: null },
      status: 'accepted' as const,
      decided_at: '2026-10-22T10:00:00Z',
    }
    const accepted = { ...sealed, status: 'accepted' as const, decided_at: '2026-10-21T10:00:00Z' }
    expect(currentBuyLevelProposal([accepted, revert])).toBeNull()
  })
})
