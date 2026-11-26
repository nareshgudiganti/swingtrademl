import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import modelsSource from '../pages/Models.tsx?raw'
import type { MLModel } from '../api/types'
import {
  ModelApprovalForm,
  buildApprovalBody,
  expectedSha,
  formProblem,
  refusalMessage,
  type ApprovalFields,
} from './ModelApprovalForm'

const SHA = 'a'.repeat(64)
const OK: ApprovalFields = {
  reason: 'Challenger beat champion on the same rows',
  verdict: 'PASS',
  sha: SHA,
  evidence: [{ path: ' docs/model-audit/r.md ', sha256: 'b'.repeat(64) }],
}
const model = (over: Partial<MLModel> = {}) =>
  ({ id: 7, name: 'ml_swing', version: 'v3', status: 'INACTIVE', metrics: { card: { artifact_sha256: SHA } }, ...over }) as MLModel
const html = (m: MLModel) =>
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ModelApprovalForm model={m} onDone={() => {}} onCancel={() => {}} />
    </QueryClientProvider>,
  )

describe('model approval form (#328)', () => {
  it('accepts a complete form and builds the server body with trimmed values', () => {
    expect(formProblem(OK)).toBeNull()
    expect(buildApprovalBody(model(), 'promote', OK)).toEqual({
      kind: 'promote',
      target: '7',
      reason: OK.reason,
      protocol_verdict: 'PASS',
      artifact_sha256: SHA,
      evidence: [{ path: 'docs/model-audit/r.md', sha256: 'b'.repeat(64) }],
    })
  })

  it('refuses anything but PASS, a short reason, a bad hash or no evidence, in plain words', () => {
    expect(formProblem({ ...OK, verdict: 'FAIL' })).toContain('Only a PASS')
    expect(formProblem({ ...OK, reason: 'short' })).toContain('at least 10')
    expect(formProblem({ ...OK, sha: 'xyz' })).toContain('fingerprint')
    expect(formProblem({ ...OK, evidence: [{ path: '', sha256: '' }] })).toContain('at least one evidence')
    expect(formProblem({ ...OK, evidence: [{ path: 'a.md', sha256: 'zz' }] })).toContain('64-character')
  })

  it('shows the file hash the server expects, from the model card', () => {
    expect(expectedSha(model())).toBe(SHA)
    expect(expectedSha(model({ metrics: undefined }))).toBe('')
    expect(html(model())).toContain(SHA)
    expect(html(model())).toContain('this is the file the server expects')
  })

  it('explains the PASS rule and offers roll back only for an archived model', () => {
    expect(html(model())).toContain('Only PASS can be approved')
    expect(html(model())).not.toContain('Go back to this older model')
    expect(html(model({ status: 'ARCHIVED' }))).toContain('Go back to this older model')
  })

  it('passes the server refusal through unchanged', () => {
    expect(refusalMessage(new Error('Model promotion is switched off.'))).toBe('Model promotion is switched off.')
  })

  it('replaces the bare Activate click on the Models screen', () => {
    expect(modelsSource).toContain('<ModelApprovalForm')
    expect(modelsSource).not.toContain('api.activateModel(id)')
  })
})
