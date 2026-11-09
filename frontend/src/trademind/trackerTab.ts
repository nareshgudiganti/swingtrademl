// The per-browser switch for the Groww Tracker menu item. Stored in this browser only (localStorage, always inside
// try/catch because it can be blocked); default ON. The page itself still opens by URL when the item is hidden.

import { useSyncExternalStore } from 'react'

export const TRACKER_TAB_KEY = 'tm_groww_tracker_tab'
const EVENT = 'tm-tracker-tab'

export function readTrackerTab(): boolean {
  try {
    return localStorage.getItem(TRACKER_TAB_KEY) !== 'off'
  } catch {
    return true
  }
}

export function writeTrackerTab(on: boolean): void {
  try {
    localStorage.setItem(TRACKER_TAB_KEY, on ? 'on' : 'off')
  } catch {
    /* blocked storage: the switch just does not stick */
  }
  try {
    window.dispatchEvent(new Event(EVENT))
  } catch {
    /* no window (tests) */
  }
}

function subscribe(cb: () => void) {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(EVENT, cb)
  window.addEventListener('storage', cb)
  return () => {
    window.removeEventListener(EVENT, cb)
    window.removeEventListener('storage', cb)
  }
}

/** True while the menu item is switched on in this browser. */
export function useTrackerTab(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, readTrackerTab, readTrackerTab)
  return [on, writeTrackerTab]
}
