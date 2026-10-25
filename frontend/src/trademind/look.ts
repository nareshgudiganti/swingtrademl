// Which TradeMind look this viewer uses: 'classic' (the dark top-menu app) or 'new' (the light sidebar app).
// A per-viewer convenience only, kept in this browser: both looks show the same pages, read the same API and
// change nothing on the server, so switching back and forth loses nothing. Classic is the default.
// `?look=new` / `?look=classic` in the address also switches (and remembers it), for sharing a link.

import { useCallback, useEffect, useState } from 'react'

export type Look = 'classic' | 'new'

export const LOOK_KEY = 'tm-look'
const EVENT = 'tm-look-change'
// The address as the page was first loaded: the app's sign-in redirects drop the query before TradeMind mounts.
let firstSearch = typeof window === 'undefined' ? '' : window.location.search

function isLook(v: unknown): v is Look {
  return v === 'classic' || v === 'new'
}

/** The look in the address (?look=…), else the saved one, else classic. Storage may be blocked: never throws. */
export function readLook(search?: string): Look {
  if (search === undefined) {
    search = (typeof window === 'undefined' ? '' : window.location.search) || firstSearch
    firstSearch = '' // used once, so a later switch in the app is not undone by the old address
  }
  const fromUrl = new URLSearchParams(search).get('look')
  if (isLook(fromUrl)) {
    saveLook(fromUrl)
    return fromUrl
  }
  try {
    const saved = window.localStorage.getItem(LOOK_KEY)
    if (isLook(saved)) return saved
  } catch {
    // private window or blocked storage: fall back to classic
  }
  return 'classic'
}

function saveLook(look: Look): void {
  try {
    window.localStorage.setItem(LOOK_KEY, look)
  } catch {
    // not remembered, but the switch still works for this visit
  }
}

/** The current look and a setter that remembers it and tells every other user of this hook. */
export function useLook(): [Look, (look: Look) => void] {
  const [look, setState] = useState<Look>(() => readLook())
  useEffect(() => {
    const onChange = (e: Event) => {
      const next = (e as CustomEvent<Look>).detail
      if (isLook(next)) setState(next)
    }
    window.addEventListener(EVENT, onChange)
    return () => window.removeEventListener(EVENT, onChange)
  }, [])
  const setLook = useCallback((next: Look) => {
    saveLook(next)
    setState(next)
    window.dispatchEvent(new CustomEvent<Look>(EVENT, { detail: next }))
  }, [])
  return [look, setLook]
}
