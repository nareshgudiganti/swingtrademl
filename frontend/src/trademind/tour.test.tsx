import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { TOUR_STEPS, Tour, TourView } from './Tour'
import {
  TOUR_STEP_COUNT,
  backStep,
  forgetTourMemory,
  markTourSeen,
  nextStep,
  shouldAutoOpen,
  tourKey,
  tourKeyAction,
  tourSeen,
  wrapFocus,
} from './tourRules'
import type { StoreGetter } from './tourRules'

function memoryStore() {
  const map = new Map<string, string>()
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
  }
}

const broken: StoreGetter = () => {
  throw new Error('SecurityError: storage is blocked')
}

/** Reads fine, refuses every write (some private browsers). */
function readOnlyStore() {
  const s = memoryStore()
  return {
    ...s,
    setItem: () => {
      throw new Error('QuotaExceededError')
    },
  }
}

beforeEach(() => forgetTourMemory())

describe('shown once per account', () => {
  it('opens for a new account, and not again once seen', () => {
    const local = memoryStore()
    const stores = [() => local]
    expect(shouldAutoOpen('asha', stores)).toBe(true)
    markTourSeen('asha', stores)
    expect(local.map.get(tourKey('asha'))).toBe('1')
    forgetTourMemory() // a fresh page load: only what was written down counts
    expect(shouldAutoOpen('asha', stores)).toBe(false)
  })

  it('is kept per account: another account on the same browser still gets it', () => {
    const local = memoryStore()
    const stores = [() => local]
    markTourSeen('asha', stores)
    forgetTourMemory()
    expect(shouldAutoOpen('ravi', stores)).toBe(true)
  })

  it('waits until we know who is signed in', () => {
    expect(shouldAutoOpen(undefined, [() => memoryStore()])).toBe(false)
  })
})

describe('when the browser will not store anything', () => {
  it('saved data blocked: falls back to this session, so at most once per session', () => {
    const session = memoryStore()
    const stores = [broken, () => session]
    expect(shouldAutoOpen('asha', stores)).toBe(true)
    markTourSeen('asha', stores)
    forgetTourMemory() // reload in the same session
    expect(shouldAutoOpen('asha', stores)).toBe(false)
  })

  it('nothing usable at all: never opens by itself (it would otherwise open on every load)', () => {
    expect(tourSeen('asha', [broken, broken])).toBe(true)
    expect(shouldAutoOpen('asha', [broken, broken])).toBe(false)
    expect(shouldAutoOpen('asha', [() => undefined, () => undefined])).toBe(false)
  })

  it('a store that reads but refuses writes is treated as unusable', () => {
    expect(shouldAutoOpen('asha', [() => readOnlyStore()])).toBe(false)
  })

  it('marking never throws, and is remembered for the rest of this page load', () => {
    expect(() => markTourSeen('asha', [broken, () => readOnlyStore()])).not.toThrow()
    const local = memoryStore()
    expect(shouldAutoOpen('asha', [() => local])).toBe(false)
  })

  it('in plain Node (no window), the default stores are unusable and nothing opens', () => {
    expect(shouldAutoOpen('asha')).toBe(false)
  })
})

describe('moving through the screens', () => {
  it('has five screens; Next and Back stop at the ends', () => {
    expect(TOUR_STEPS).toHaveLength(5)
    expect(TOUR_STEP_COUNT).toBe(5)
    expect(nextStep(0)).toBe(1)
    expect(nextStep(4)).toBe(4)
    expect(backStep(1)).toBe(0)
    expect(backStep(0)).toBe(0)
  })

  it('Escape closes, arrow keys move, other keys do nothing', () => {
    expect(tourKeyAction('Escape')).toBe('close')
    expect(tourKeyAction('Esc')).toBe('close')
    expect(tourKeyAction('ArrowRight')).toBe('next')
    expect(tourKeyAction('ArrowLeft')).toBe('back')
    expect(tourKeyAction('a')).toBe('none')
    expect(tourKeyAction('Enter')).toBe('none')
  })

  it('Tab wraps around inside the tour', () => {
    expect(wrapFocus(2, 3, false)).toBe(0) // last -> first
    expect(wrapFocus(0, 3, true)).toBe(2) // first, Shift+Tab -> last
    expect(wrapFocus(1, 3, false)).toBeNull() // middle: the browser moves it
    expect(wrapFocus(-1, 3, false)).toBe(0) // from outside: brought back in
    expect(wrapFocus(-1, 3, true)).toBe(2)
    expect(wrapFocus(-1, 0, false)).toBeNull()
  })
})

const text = (html: string) =>
  html
    .replace(/<!-- -->/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

const noop = () => {}
function view(step: number, realAccount = false) {
  return renderToString(
    <MemoryRouter>
      <TourView step={step} audience={{ realAccount }} id="t" onNext={noop} onBack={noop} onClose={noop} />
    </MemoryRouter>,
  )
}

describe('the screens', () => {
  it('is a labelled modal dialog with a close button and a step count', () => {
    const html = view(0)
    expect(html).toContain('role="dialog"')
    expect(html).toContain('aria-modal="true"')
    expect(html).toContain('aria-labelledby="t-title"')
    expect(html).toContain('id="t-title"')
    expect(html).toContain('aria-label="Close the tour"')
    expect(text(html)).toContain('Step 1 of 5')
  })

  it('Back is off on the first screen, and the last screen ends with Done', () => {
    expect(view(0)).toMatch(/<button[^>]*disabled[^>]*>Back<\/button>/)
    expect(text(view(4))).toContain('Done')
    expect(text(view(3))).toContain('Next')
  })

  it('screen 1 shows every decision word and market mode through the one glossary', () => {
    const t = text(view(0))
    for (const w of ['BUY', 'WATCH', 'WAIT', 'AVOID', 'HOLD', 'MONITOR', 'REDUCE', 'EXIT', 'Normal', 'Careful', 'No new trades'])
      expect(t).toContain(w)
    expect(view(0)).toContain('tm-term-btn') // tappable explanations, not copied text
  })

  it('screen 3 never calls the score a chance or a probability', () => {
    const t = text(view(2))
    expect(t).toContain('It is not a chance of winning')
    expect(t).toContain('practice mode')
    expect(t).not.toMatch(/probability|\d+% chance|likely to win|guarantee/i)
  })

  it('screen 4 has the plan numbers from the code', () => {
    const t = text(view(3))
    for (const s of ['8% above', '4% below', 'up 5%', '15 trading days']) expect(t).toContain(s)
  })

  it('never points an account to the real-money page it cannot open', () => {
    for (const step of [1, 4]) {
      expect(view(step, false)).not.toContain('/trademind/holdings')
      expect(text(view(step, false))).not.toContain('My Zerodha')
    }
    expect(view(4, true)).toContain('/trademind/holdings')
    expect(text(view(1, true))).toContain('My Zerodha (Real)')
  })

  it('every page it links to is one every account can open', () => {
    const links = [...view(4, false).matchAll(/href="([^"]+)"/g)].map((m) => m[1])
    expect(links.sort()).toEqual(
      ['/trademind', '/trademind/learn', '/trademind/opportunities', '/trademind/positions', '/trademind/records'].sort(),
    )
  })
})

describe('the Help button', () => {
  it('is always in the top bar, closed until asked (it reopens the tour)', () => {
    const html = renderToString(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <Tour realAccount={false} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(html).toContain('data-testid="help"')
    expect(html).toContain('aria-haspopup="dialog"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain('role="dialog"')
  })
})
