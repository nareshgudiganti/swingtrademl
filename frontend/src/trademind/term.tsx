// Tap any marked word to see what it means. <Term k="drawdown">drawdown</Term> wraps a word in a button;
// tapping, clicking or pressing Enter/Space on it opens a small box with the plain explanation from the one
// glossary in vocab.ts. Escape, the Close button, tapping elsewhere or tabbing away closes it.
// Display only: it never changes what the word is, only explains it.

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode, Ref, SyntheticEvent } from 'react'

import { GLOSSARY, GLOSSARY_GROUPS, isGlossaryKey, wordLabel, wordTagColor } from './vocab'
import type { GlossaryKey } from './vocab'

/** What a key press does while the explanation is open. */
export function termKeyAction(key: string, open: boolean): 'close' | 'none' {
  return open && (key === 'Escape' || key === 'Esc') ? 'close' : 'none'
}

/** Where the box goes: under the word, or above it when there is no room below; always inside the screen. */
export function popoverPosition(
  rect: { left: number; top: number; bottom: number },
  viewport: { width: number; height: number },
): CSSProperties {
  const gutter = 16
  const width = Math.min(300, viewport.width - gutter * 2)
  const left = Math.max(gutter, Math.min(rect.left, viewport.width - width - gutter))
  const roomBelow = viewport.height - rect.bottom
  return roomBelow >= 170 || roomBelow >= rect.top
    ? { position: 'fixed', left, top: rect.bottom + 6, width }
    : { position: 'fixed', left, bottom: viewport.height - rect.top + 6, width }
}

const stop = (e: SyntheticEvent) => e.stopPropagation()

type ViewProps = {
  k: GlossaryKey
  children: ReactNode
  open: boolean
  id: string
  onToggle?: () => void
  onClose?: () => void
  style?: CSSProperties
  buttonRef?: Ref<HTMLButtonElement>
  boxRef?: Ref<HTMLSpanElement>
}

/** The markup, without state — so it can be checked without a browser. */
export function TermView({ k, children, open, id, onToggle, onClose, style, buttonRef, boxRef }: ViewProps) {
  const entry = GLOSSARY[k]
  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (termKeyAction(e.key, open) === 'close') {
      e.preventDefault()
      e.stopPropagation()
      onClose?.()
    }
  }
  const box = open ? (
    <span
      ref={boxRef}
      id={id}
      role="dialog"
      aria-labelledby={`${id}-title`}
      tabIndex={-1}
      className="tm-term-box"
      style={style}
      onClick={stop}
      onPointerDown={stop}
      onKeyDown={onKeyDown}
    >
      <span className="tm-term-title" id={`${id}-title`}>
        {entry.label}
      </span>
      <span className="tm-term-text">{entry.text}</span>
      <button type="button" className="tm-term-close" onClick={onClose}>
        Close
      </button>
    </span>
  ) : null
  return (
    <span className="tm-term">
      <button
        ref={buttonRef}
        type="button"
        className={typeof children === 'string' ? 'tm-term-btn tm-term-word' : 'tm-term-btn'}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? id : undefined}
        onClick={(e) => {
          e.stopPropagation()
          onToggle?.()
        }}
        onKeyDown={onKeyDown}
      >
        {children}
        <span className="tm-sr-only"> (what does this mean?)</span>
      </button>
      {box}
    </span>
  )
}

/** A word that explains itself when tapped. `k` is its glossary key; the children are what is shown. */
export function Term({ k, children }: { k: GlossaryKey; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [style, setStyle] = useState<CSSProperties | undefined>(undefined)
  const id = `tm-term-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const buttonRef = useRef<HTMLButtonElement>(null)
  const boxRef = useRef<HTMLSpanElement>(null)

  const close = useCallback((refocus = true) => {
    setOpen(false)
    if (refocus) buttonRef.current?.focus()
  }, [])

  const place = useCallback(() => {
    const b = buttonRef.current
    if (b) setStyle(popoverPosition(b.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }))
  }, [])

  useLayoutEffect(() => {
    if (!open) return
    place()
    boxRef.current?.focus()
  }, [open, place])

  useEffect(() => {
    if (!open) return
    const inside = (t: EventTarget | null) =>
      t instanceof Node && (buttonRef.current?.contains(t) || boxRef.current?.contains(t))
    const onDown = (e: PointerEvent) => {
      if (!inside(e.target)) close(false)
    }
    const onFocus = (e: FocusEvent) => {
      if (!inside(e.target)) close(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (termKeyAction(e.key, true) === 'close') close()
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('focusin', onFocus)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('focusin', onFocus)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, close, place])

  return (
    <TermView
      k={k}
      id={id}
      open={open}
      style={style}
      buttonRef={buttonRef}
      boxRef={boxRef}
      onToggle={() => setOpen((o) => !o)}
      onClose={() => close()}
    >
      {children}
    </TermView>
  )
}

/** A brain word (TRADE, HOLD, EXIT…) as a coloured tag that explains itself. Unknown words show as a plain tag. */
export function WordTag({ word }: { word: string }) {
  const tag = <span className={`tm-tag tm-tag-${wordTagColor(word)}`}>{wordLabel(word)}</span>
  return isGlossaryKey(word) ? <Term k={word}>{tag}</Term> : tag
}

/** Like <Term>, for a word that comes from the server: explained when the glossary knows it, plain otherwise. */
export function TermIf({ k, children }: { k: string | null | undefined; children: ReactNode }) {
  return k && isGlossaryKey(k) ? <Term k={k}>{children}</Term> : <>{children}</>
}

/** Every word in the glossary, grouped, as a plain list (the Learn page shows it). */
export function Glossary() {
  return (
    <section className="tm-card tm-glossary" id="glossary" aria-labelledby="tm-glossary-title">
      <header className="tm-card-head">
        <div>
          <h3 className="tm-card-title" id="tm-glossary-title">
            What the words mean
          </h3>
          <div className="tm-card-sub">Tap a dotted word or a coloured word anywhere in the app to see this.</div>
        </div>
      </header>
      {GLOSSARY_GROUPS.map((g) => (
        <div key={g.id}>
          <div className="tm-strong" style={{ marginTop: '0.9rem' }}>
            {g.title}
          </div>
          <dl style={{ margin: 0 }}>
            {(Object.keys(GLOSSARY) as GlossaryKey[])
              .filter((k) => GLOSSARY[k].group === g.id)
              .map((k) => (
                <div key={k}>
                  <dt>{GLOSSARY[k].label}</dt>
                  <dd>{GLOSSARY[k].text}</dd>
                </div>
              ))}
          </dl>
        </div>
      ))}
    </section>
  )
}
