import { describe, expect, it } from 'vitest'

import { stopCheckWarning } from './stopCheckWarning'

describe('stopCheckWarning', () => {
  it('says nothing while Zerodha is connected', () => {
    expect(stopCheckWarning(true, 3, { bot: 3, testing: 1, real: 2 })).toBeNull()
  })

  it('keeps real holdings in the warning, listed apart from paper', () => {
    const text = stopCheckWarning(false, 0, { bot: 0, testing: 0, real: 2 })
    expect(text).toContain('My Holdings (real money) 2')
  })

  it('lists each book separately and never adds them up', () => {
    const text = stopCheckWarning(false, 2, { bot: 2, testing: 1, real: 3 })!
    expect(text).toContain('Bot (paper) 2')
    expect(text).toContain('Testing (paper) 1')
    expect(text).toContain('My Holdings (real money) 3')
    expect(text).not.toContain('6')
  })

  it('says nothing when no book has an open position', () => {
    expect(stopCheckWarning(false, 0, { bot: 0, testing: 0, real: 0 })).toBeNull()
  })

  it('falls back to the bot count from an older API', () => {
    expect(stopCheckWarning(false, 4)).toContain('Bot (paper) 4')
  })
})
