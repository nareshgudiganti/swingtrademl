import { useEffect } from 'react'
import type { ReactNode } from 'react'

/** Generic centered dialog — backdrop click or Escape closes it. Used
 * wherever a row needs its full detail without permanently occupying page
 * space (see Suggestions: a table you scan, not a split-pane you keep open). */
export default function Modal({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">
          ✕
        </button>
        {children}
      </div>
    </div>
  )
}
