import { describe, expect, it } from 'vitest'

import type { BrainAlertRecord } from '../api/types'
import { SEEN_KEY, bellLabel, latestId, readSeen, stageChip, unseenCount, writeSeen } from './bellRules'

const alert = (id: number): BrainAlertRecord => ({
  id,
  kind: 'trade',
  text: `Alert ${id}`,
  alert_date: '2026-10-20',
  sent_at: '2026-10-20T10:20:00+00:00',
  channel: 'telegram',
})

function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, String(v)),
  }
}

const broken = {
  getItem: () => {
    throw new Error('blocked')
  },
  setItem: () => {
    throw new Error('blocked')
  },
} as unknown as Storage

describe('unseen alerts', () => {
  it('counts only alerts newer than the last one seen', () => {
    expect(unseenCount([alert(5), alert(4), alert(3)], 3)).toBe(2)
    expect(unseenCount([alert(5)], 5)).toBe(0)
    expect(unseenCount([], 0)).toBe(0)
  })

  it('the newest id is what opening the bell marks as seen', () => {
    expect(latestId([alert(3), alert(9), alert(4)])).toBe(9)
    expect(latestId([])).toBe(0)
  })
})

describe('seen is kept in this browser only', () => {
  it('round-trips through storage', () => {
    const s = memoryStorage()
    expect(readSeen(s)).toBe(0)
    writeSeen(7, s)
    expect(s.getItem(SEEN_KEY)).toBe('7')
    expect(readSeen(s)).toBe(7)
  })

  it('never goes backwards (an older list does not un-see newer alerts)', () => {
    const s = memoryStorage()
    writeSeen(9, s)
    writeSeen(4, s)
    expect(readSeen(s)).toBe(9)
  })

  it('blocked or junk storage is treated as nothing seen, and never throws', () => {
    expect(readSeen(broken)).toBe(0)
    expect(() => writeSeen(3, broken)).not.toThrow()
    const s = memoryStorage()
    s.setItem(SEEN_KEY, 'not a number')
    expect(readSeen(s)).toBe(0)
    expect(readSeen(undefined)).toBe(0)
  })
})

describe('labels', () => {
  it('the bell says how many are new, for a screen reader too', () => {
    expect(bellLabel(0)).toBe('Alerts')
    expect(bellLabel(1)).toBe('Alerts, 1 new')
    expect(bellLabel(3)).toBe('Alerts, 3 new')
  })

  it('the stage chip names each stage in plain words', () => {
    expect(stageChip('shadow').label).toBe('Practice')
    expect(stageChip('approval').label).toBe('Approval')
    expect(stageChip('auto').label).toBe('Auto')
  })
})
