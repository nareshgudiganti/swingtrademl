import { useEffect, useRef, useState } from 'react'

import { registerStepUpHandler, type StepUpKind } from '../api/client'
import { Enrol, SecondStep } from '../pages/AdminUsers'

/**
 * Mounted once. When a privileged admin call is refused for lack of the two-step code, this asks the admin
 * for it (or walks them through setup first), then the original call is repeated. Cancel = the call fails.
 */
export default function AdminStepUpHost() {
  const [kind, setKind] = useState<StepUpKind | null>(null)
  const resolver = useRef<((token: string | null) => void) | null>(null)

  useEffect(() => {
    registerStepUpHandler(
      (k) =>
        new Promise<string | null>((resolve) => {
          resolver.current?.(null)
          resolver.current = resolve
          setKind(k)
        }),
    )
    return () => registerStepUpHandler(null)
  }, [])

  function finish(token: string | null) {
    resolver.current?.(token)
    resolver.current = null
    setKind(null)
  }

  if (!kind) return null
  return (
    <div className="tm-dialog-backdrop" onClick={() => finish(null)}>
      <div
        className="tm-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Admin two-step check"
        onClick={(e) => e.stopPropagation()}
      >
        {kind === 'enrol' ? <Enrol onDone={finish} /> : <SecondStep onToken={finish} />}
        <button className="btn-link" style={{ marginTop: 12 }} onClick={() => finish(null)}>
          Cancel
        </button>
      </div>
    </div>
  )
}
