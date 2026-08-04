import type { ReactNode } from 'react'

interface Props {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: 'pos' | 'neg' | 'flat'
}

export default function Stat({ label, value, sub, tone }: Props) {
  return (
    <div className="card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone ?? ''}`}>{value}</div>
      {sub !== undefined && <div className="stat-sub">{sub}</div>}
    </div>
  )
}
