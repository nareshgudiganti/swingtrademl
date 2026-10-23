// ob15: if the Observatory page itself breaks while drawing, show a plain message, not a blank screen.
import { Component } from 'react'
import type { ReactNode } from 'react'

import { Card } from '../ui'

export function ObservatoryCrash({ error }: { error: unknown }) {
  return (
    <div className="tm-page" data-testid="obs-crash">
      <Card title="Brain Observatory" sub="Owner only · Read-only">
        <h3>This page could not be drawn.</h3>
        <p>Nothing was changed: the Observatory only reads records. Reload the page to try again.</p>
        <p className="tm-note">Page said: {error instanceof Error ? error.message : String(error)}</p>
      </Card>
    </div>
  )
}

export class ObservatoryBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state: { error: unknown } = { error: null }

  static getDerivedStateFromError(error: unknown): { error: unknown } {
    return { error: error ?? new Error('unknown error') }
  }

  render() {
    return this.state.error ? <ObservatoryCrash error={this.state.error} /> : this.props.children
  }
}
