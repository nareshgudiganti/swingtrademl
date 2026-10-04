// One confirmation dialog for every TradeMind action that changes something
// (stop trades, close a position, approve an idea…). It says in plain words
// what will happen, can ask for a short reason, and shows the server's own
// error if the action is refused — it never closes on a failure.
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

export function Confirm({
  title,
  children,
  confirmLabel,
  danger = false,
  reason,
  onConfirm,
  onClose,
}: {
  title: string
  /** What will happen, in plain words. */
  children: ReactNode
  confirmLabel: string
  /** Red button for actions that sell, stop or cannot be undone. */
  danger?: boolean
  /** Ask for a short typed reason; the button stays off until one is given. */
  reason?: { label: string; placeholder?: string; required?: boolean }
  /** Runs the action; throw (or reject) to keep the dialog open with the error. */
  onConfirm: (reason: string) => Promise<unknown> | unknown
  onClose: () => void
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const needsReason = reason?.required !== false && reason != null
  const blocked = busy || (needsReason && text.trim() === '')

  async function run() {
    setBusy(true)
    setError(null)
    try {
      await onConfirm(text.trim())
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="tm-dialog-backdrop" onClick={() => !busy && onClose()}>
      <div className="tm-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="tm-strong" style={{ fontSize: '1rem', marginBottom: '0.5rem' }}>
          {title}
        </div>
        <div className="tm-dim" style={{ marginBottom: '0.8rem' }}>
          {children}
        </div>
        {reason && (
          <label style={{ display: 'block', marginBottom: '0.8rem' }}>
            <span className="tm-dim" style={{ fontSize: '0.75rem' }}>
              {reason.label}
            </span>
            <input
              className="tm-input"
              style={{ width: '100%', marginTop: 4 }}
              placeholder={reason.placeholder}
              value={text}
              autoFocus
              onChange={(e) => setText(e.target.value)}
            />
          </label>
        )}
        {error && (
          <p className="tm-neg" style={{ margin: '0 0 0.8rem' }}>
            {error}
          </p>
        )}
        <div className="tm-flex" style={{ justifyContent: 'flex-end', gap: '0.5rem' }}>
          <button className="tm-btn tm-btn-ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className={`tm-btn ${danger ? 'tm-btn-danger' : ''}`} onClick={run} disabled={blocked}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
