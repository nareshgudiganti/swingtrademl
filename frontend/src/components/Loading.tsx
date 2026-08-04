export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="empty">{label}</div>
}

export function Empty({ label }: { label: string }) {
  return <div className="empty">{label}</div>
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error)
  return <div className="banner banner-warn">Could not load: {message}</div>
}
