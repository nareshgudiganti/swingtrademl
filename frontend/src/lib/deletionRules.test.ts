import { describe, expect, it } from 'vitest'

import { deletionErrorText, deletionLinkKind, deletionView, type DeletionStatus } from './deletionRules'

const base: DeletionStatus = { enabled: true, protected: false, grace_days: 14, status: null, scheduled_for: null }

describe('deletionView: where the request stands', () => {
  it('nothing asked: offers the button and names the grace period', () => {
    const v = deletionView(base)
    expect(v.state).toBe('none')
    expect(v.canRequest).toBe(true)
    expect(v.detail).toContain('14 days')
  })

  it('link emailed: says nothing is deleted yet and lets them send it again', () => {
    const v = deletionView({ ...base, status: 'pending' })
    expect(v.state).toBe('requested')
    expect(v.detail).toContain('Nothing is deleted')
    expect(v.requestLabel).toBe('Send the link again')
  })

  it('grace period: shows the date and offers no new request', () => {
    const v = deletionView({ ...base, status: 'scheduled', scheduled_for: '2026-11-25T10:00:00+00:00' })
    expect(v.state).toBe('scheduled')
    expect(v.headline).toContain('25 Nov 2026')
    expect(v.canRequest).toBe(false)
  })

  it('cancelled: says the account is kept and allows asking again', () => {
    const v = deletionView({ ...base, status: 'cancelled' })
    expect(v.state).toBe('kept')
    expect(v.canRequest).toBe(true)
  })

  it('the owner account is protected and has no button', () => {
    const v = deletionView({ ...base, protected: true, status: 'pending' })
    expect(v.state).toBe('protected')
    expect(v.canRequest).toBe(false)
  })
})

describe('deletionErrorText', () => {
  it('says plainly when deletion is not open (404)', () => {
    expect(deletionErrorText(404, 'Not found')).toBe('Deleting an account is not open yet.')
  })
  it('keeps the server wording for a refused password', () => {
    expect(deletionErrorText(400, 'That password is not right.')).toBe('That password is not right.')
  })
  it('says nothing was changed when the Pro cancel failed (502)', () => {
    expect(deletionErrorText(502, '')).toContain('nothing was changed')
  })
})

describe('deletionLinkKind', () => {
  it('knows the two email links, with or without a trailing slash', () => {
    expect(deletionLinkKind('/confirm-deletion')).toBe('confirm')
    expect(deletionLinkKind('/cancel-deletion/')).toBe('keep')
    expect(deletionLinkKind('/trademind/account')).toBeNull()
  })
})
