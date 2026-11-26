import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { api } from '../api/client'
import type { MLModel, ModelApprovalBody } from '../api/types'

// Owner-only form for the model promotion safeguard (#328). Step 1 records the owner's approval; step 2 spends it
// to activate (or roll back) the model. The server decides everything: its refusal is shown word for word.

export interface EvidenceRow {
  path: string
  sha256: string
}

export interface ApprovalFields {
  reason: string
  verdict: string
  sha: string
  evidence: EvidenceRow[]
}

const SHA = /^[0-9a-f]{64}$/
export const MIN_REASON = 10

/** The hash the server expects for this model's file: the one in its model card, if it has one. */
/** The server's own words, untouched (switch off, hash differs, approval expired...). */
export function refusalMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function Refusal({ error }: { error: unknown }) {
  return (
    <div className="banner banner-warn" role="alert">
      Refused: {refusalMessage(error)}
    </div>
  )
}

export function expectedSha(model: Pick<MLModel, 'metrics'>): string {
  const card = (model.metrics as { card?: { artifact_sha256?: unknown } } | undefined)?.card
  return typeof card?.artifact_sha256 === 'string' ? card.artifact_sha256 : ''
}

/** Why the form cannot be sent yet, in plain English; null when it can. */
export function formProblem(f: ApprovalFields): string | null {
  if (f.reason.trim().length < MIN_REASON) return `Write a reason of at least ${MIN_REASON} characters.`
  if (f.verdict !== 'PASS') return 'Only a PASS result can be approved. Anything else is refused.'
  if (!SHA.test(f.sha.trim())) return "Enter the model file's fingerprint (64 letters and digits, a to f)."
  const rows = f.evidence.filter((e) => e.path.trim() || e.sha256.trim())
  if (rows.length === 0) return 'Add at least one evidence file with its fingerprint.'
  if (rows.some((e) => !e.path.trim() || !SHA.test(e.sha256.trim()))) {
    return 'Each evidence file needs a path and a 64-character fingerprint.'
  }
  return null
}

export function buildApprovalBody(
  model: Pick<MLModel, 'id'>,
  kind: 'promote' | 'rollback',
  f: ApprovalFields,
): ModelApprovalBody {
  return {
    kind,
    target: String(model.id),
    reason: f.reason.trim(),
    protocol_verdict: f.verdict,
    artifact_sha256: f.sha.trim(),
    evidence: f.evidence
      .filter((e) => e.path.trim() || e.sha256.trim())
      .map((e) => ({ path: e.path.trim(), sha256: e.sha256.trim() })),
  }
}

export function ModelApprovalForm({
  model,
  onDone,
  onCancel,
}: {
  model: MLModel
  onDone: () => void
  onCancel: () => void
}) {
  const canRollBack = model.status === 'ARCHIVED'
  const [kind, setKind] = useState<'promote' | 'rollback'>('promote')
  const [reason, setReason] = useState('')
  const [verdict, setVerdict] = useState('PASS')
  const [sha, setSha] = useState(expectedSha(model))
  const [evidence, setEvidence] = useState<EvidenceRow[]>([{ path: '', sha256: '' }])
  const [approvalId, setApprovalId] = useState<number | null>(null)

  const form: ApprovalFields = { reason, verdict, sha, evidence }
  const problem = formProblem(form)
  const locked = approvalId !== null

  const record = useMutation({
    mutationFn: () => api.recordModelApproval(buildApprovalBody(model, kind, form)),
    onSuccess: (r) => setApprovalId(r.approval_id),
  })
  const use = useMutation({
    mutationFn: () =>
      kind === 'rollback' ? api.rollbackModel(model.id, approvalId!) : api.activateModel(model.id, approvalId!),
    onSuccess: onDone,
  })

  const setRow = (i: number, patch: Partial<EvidenceRow>) =>
    setEvidence((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  return (
    <div className="card" style={{ marginTop: '1rem' }} data-testid="model-approval-form">
      <h3 style={{ marginTop: 0 }}>
        Approve a change to {model.name}:{model.version}
      </h3>
      <p className="muted">
        A model only goes live after you record your approval here and then use it once. The server checks the
        evidence files, and refuses everything while the promotion switch is off.
      </p>

      <div className="field">
        <label htmlFor="appr-kind">What do you want to do?</label>
        <select
          id="appr-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as 'promote' | 'rollback')}
          disabled={locked}
        >
          <option value="promote">Put this model live</option>
          {canRollBack && <option value="rollback">Go back to this older model</option>}
        </select>
      </div>

      <div className="field">
        <label htmlFor="appr-reason">Why are you approving this? (at least {MIN_REASON} characters)</label>
        <textarea id="appr-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} disabled={locked} />
      </div>

      <div className="field">
        <label htmlFor="appr-verdict">Result of the test protocol</label>
        <select id="appr-verdict" value={verdict} onChange={(e) => setVerdict(e.target.value)} disabled={locked}>
          <option value="PASS">PASS</option>
          <option value="FAIL">FAIL</option>
          <option value="INCONCLUSIVE">INCONCLUSIVE</option>
        </select>
        <div className="muted" style={{ fontSize: '0.8rem' }}>
          Only PASS can be approved. If the test failed or was not conclusive, the approval is refused.
        </div>
      </div>

      <div className="field">
        <label htmlFor="appr-sha">Model file fingerprint (sha256)</label>
        <input id="appr-sha" value={sha} onChange={(e) => setSha(e.target.value)} disabled={locked} />
        <div className="muted" style={{ fontSize: '0.8rem' }}>
          {expectedSha(model)
            ? 'Filled in from the model card: this is the file the server expects.'
            : 'This model has no model card with a fingerprint, so the server will not put it live.'}
        </div>
      </div>

      <div className="field">
        <label>Evidence files (reports saved in the project, with their fingerprints)</label>
        {evidence.map((row, i) => (
          <div key={i} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.4rem', flexWrap: 'wrap' }}>
            <input
              aria-label={`Evidence file path ${i + 1}`}
              placeholder="docs/model-audit/report.md"
              value={row.path}
              onChange={(e) => setRow(i, { path: e.target.value })}
              disabled={locked}
              style={{ flex: '1 1 14rem' }}
            />
            <input
              aria-label={`Evidence file fingerprint ${i + 1}`}
              placeholder="sha256 of that file"
              value={row.sha256}
              onChange={(e) => setRow(i, { sha256: e.target.value })}
              disabled={locked}
              style={{ flex: '2 1 20rem' }}
            />
            {evidence.length > 1 && !locked && (
              <button type="button" onClick={() => setEvidence((rows) => rows.filter((_, j) => j !== i))}>
                Remove
              </button>
            )}
          </div>
        ))}
        {!locked && (
          <button type="button" onClick={() => setEvidence((rows) => [...rows, { path: '', sha256: '' }])}>
            Add another evidence file
          </button>
        )}
        <div className="muted" style={{ fontSize: '0.8rem' }}>
          The server reads each file again and refuses if it is missing or has changed since its fingerprint was taken.
        </div>
      </div>

      {!locked ? (
        <>
          {problem && <p className="muted">{problem}</p>}
          {record.error && <Refusal error={record.error} />}
          <button className="primary" onClick={() => record.mutate()} disabled={!!problem || record.isPending}>
            Record my approval
          </button>
        </>
      ) : (
        <>
          <p>Approval #{approvalId} is recorded. It can be used once, within 7 days.</p>
          {use.error && <Refusal error={use.error} />}
          <button className="primary" onClick={() => use.mutate()} disabled={use.isPending}>
            {kind === 'rollback' ? 'Go back to this model now' : 'Put this model live now'}
          </button>
        </>
      )}{' '}
      <button type="button" onClick={onCancel}>
        Close
      </button>
    </div>
  )
}
