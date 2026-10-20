// The first-time tour (ux5): the rules that are not drawing. Whether this account has already seen the tour, what a
// key press does, and where focus goes next. Pure functions, so they can be tested without a browser; Tour.tsx
// draws the screens.
//
// "Seen" is kept in this browser, per account (there is no per-user settings store on the server, and adding one
// would need a database migration). It is written as soon as the tour opens, so a person sees it once even if they
// close the tab half-way. If the browser will not let us store anything, the tour is never opened by itself (it
// would otherwise open on every page load); the Help button still opens it.

export const TOUR_STEP_COUNT = 5

/** The browser key for one account. Bump the version to show a rewritten tour to everyone once more. */
export function tourKey(username: string): string {
  return `tm.tour.seen.v1:${username}`
}

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
/** Each getter may throw (a blocked or private browser), so it is only ever called inside try. */
export type StoreGetter = () => Store | undefined

const browserStores: StoreGetter[] = [
  () => (typeof window === 'undefined' ? undefined : window.localStorage),
  () => (typeof window === 'undefined' ? undefined : window.sessionStorage),
]

// Accounts that saw the tour since this page loaded, for when nothing could be written down.
const seenThisLoad = new Set<string>()

/** For tests only. */
export function forgetTourMemory(): void {
  seenThisLoad.clear()
}

/** A store we can both read and write. A store that reads but refuses writes would show the tour on every load. */
function usable(get: StoreGetter): Store | undefined {
  try {
    const s = get()
    if (!s) return undefined
    const probe = 'tm.tour.probe'
    s.setItem(probe, '1')
    s.removeItem(probe)
    return s
  } catch {
    return undefined
  }
}

/**
 * Whether this account has seen the tour. Checked in this browser's saved data first, then in this browser
 * session's data. When neither can be used, the answer is "seen", so the tour never opens by itself on every load.
 */
export function tourSeen(username: string, stores: StoreGetter[] = browserStores): boolean {
  if (seenThisLoad.has(username)) return true
  let anyUsable = false
  for (const get of stores) {
    const s = usable(get)
    if (!s) continue
    anyUsable = true
    try {
      if (s.getItem(tourKey(username)) === '1') return true
    } catch {
      /* treated as not written in this store */
    }
  }
  return !anyUsable
}

/** Write down that this account has seen the tour, everywhere we can. Never throws. */
export function markTourSeen(username: string, stores: StoreGetter[] = browserStores): void {
  seenThisLoad.add(username)
  for (const get of stores) {
    try {
      get()?.setItem(tourKey(username), '1')
    } catch {
      /* the next store, or this page load's memory, keeps it */
    }
  }
}

/** Open the tour by itself? Only once we know who is signed in, and only if they have not seen it. */
export function shouldAutoOpen(username: string | undefined, stores: StoreGetter[] = browserStores): boolean {
  return !!username && !tourSeen(username, stores)
}

export type TourKeyAction = 'close' | 'next' | 'back' | 'none'

/** Escape closes; the left and right arrow keys move between screens. */
export function tourKeyAction(key: string): TourKeyAction {
  if (key === 'Escape' || key === 'Esc') return 'close'
  if (key === 'ArrowRight') return 'next'
  if (key === 'ArrowLeft') return 'back'
  return 'none'
}

export function nextStep(step: number, count = TOUR_STEP_COUNT): number {
  return Math.min(step + 1, count - 1)
}

export function backStep(step: number): number {
  return Math.max(step - 1, 0)
}

/**
 * Keeping keyboard focus inside the tour: given where focus is among the tour's `count` focusable things
 * (-1 = somewhere else), the one Tab (or Shift+Tab) should move to, or null to let the browser move as usual.
 */
export function wrapFocus(current: number, count: number, backwards: boolean): number | null {
  if (count === 0) return null
  if (current === -1) return backwards ? count - 1 : 0
  if (backwards && current === 0) return count - 1
  if (!backwards && current === count - 1) return 0
  return null
}
