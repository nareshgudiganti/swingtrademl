import { describe, expect, it } from 'vitest'

import appSource from '../App.tsx?raw'
import { planText } from './AdminUsers'

describe('admin screen', () => {
  it('is an owner-only route, never a normal menu entry', () => {
    const line = appSource.split('\n').find((l) => l.includes("to: '/admin'")) ?? ''
    expect(line).toContain('manage: true')
    expect(line).not.toContain('inNav')
  })

  it('says where each plan comes from', () => {
    const base = { stored_plan: 'free', effective_plan: 'free', has_active_grant: false, subscription_status: null }
    expect(planText(base)).toBe('Free')
    expect(planText({ ...base, stored_plan: 'pro', effective_plan: 'pro' })).toBe('Pro (set by admin)')
    expect(planText({ ...base, effective_plan: 'pro', has_active_grant: true })).toBe('Pro (free gift)')
    expect(planText({ ...base, effective_plan: 'pro', subscription_status: 'active' })).toBe('Pro (paid)')
  })
})
