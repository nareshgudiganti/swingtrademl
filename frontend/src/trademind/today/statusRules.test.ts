// oa5: the safety lines on Today's status strip. Unknown always leans towards caution.
import { describe, expect, it } from 'vitest'

import type { BrainStage, SystemState } from '../../api/types'
import { drawdownLine, killSwitchLine, stageLine } from './statusRules'

const on: SystemState = { new_entries_enabled: true, exits_enabled: true, halt_reason: null, halted_at: null, halted_by: null }

describe('kill switch', () => {
  it('on: new buys allowed', () => {
    expect(killSwitchLine(on, false)).toMatchObject({ value: 'Allowed', tone: 'green' })
  })

  it('halted: paused, with the reason and who', () => {
    const l = killSwitchLine({ ...on, new_entries_enabled: false, halt_reason: 'Data problem', halted_by: 'owner' }, false)
    expect(l).toMatchObject({ value: 'Paused by the kill switch', tone: 'red' })
    expect(l.note).toBe('Reason: Data problem, by owner.')
  })

  it('exits switched off is a warning even while buys are allowed', () => {
    expect(killSwitchLine({ ...on, exits_enabled: false }, false)).toMatchObject({
      tone: 'amber',
      note: 'Automatic selling at the stop or target is switched off.',
    })
  })

  it('could not be read: treat new buys as paused, never "Allowed"', () => {
    const l = killSwitchLine(undefined, true)
    expect(l.tone).toBe('red')
    expect(l.value).not.toBe('Allowed')
    expect(l.note).toContain('Treat new buys as paused')
  })
})

describe('drawdown', () => {
  it('below the halt', () => {
    expect(drawdownLine(3, 15, false)).toMatchObject({ value: '3.0% below its peak', note: 'New buys stop at 15%.', tone: 'green' })
  })

  it('getting close turns amber', () => {
    expect(drawdownLine(11, 15, false).tone).toBe('amber')
  })

  it('at the halt: new buys paused', () => {
    const l = drawdownLine(15.2, 15, false)
    expect(l.tone).toBe('red')
    expect(l.note).toContain('new buys are paused')
  })

  it('no history yet says so, never 0%', () => {
    expect(drawdownLine(null, 15, false)).toMatchObject({ value: 'Not available', note: 'No account history yet.' })
  })

  it('a failed load says not available', () => {
    expect(drawdownLine(null, null, true).value).toBe('Not available')
  })
})

describe('stage', () => {
  const stage = (s: BrainStage['stage']) => ({ stage: s, plain: '', finished: 0, needed: 30, ready: false, history: [] }) as BrainStage

  it('names the stage the way the top bar does', () => {
    expect(stageLine(stage('shadow'), false).value).toBe('Practice')
    expect(stageLine(stage('approval'), false).value).toBe('Approval')
    expect(stageLine(stage('auto'), false).value).toBe('Auto')
  })

  it('could not be read', () => {
    expect(stageLine(undefined, true).value).toBe('Not available')
  })
})
