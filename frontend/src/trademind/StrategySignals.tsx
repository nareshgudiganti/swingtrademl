// oa5: the version 1 bot's per-strategy signals as a read-only list in Discover (owner decision 2026-10-16; it
// replaces the classic Dashboard's "Why isn't more showing up here?" box). Display only: nothing here buys or sells.
//
// These are the version 1 strategies' own signals, not the brain's ideas. Their models ask a different question
// (does the price close 2% or more higher within 5 days), a second horizon the owner intends to keep. Every signal
// is "Experimental, unproven", and the model score is a ranking, never shown with a % sign.
//
// GET /strategies and /strategies/{id}/signals are not opened to any plan, so only accounts that see the whole app
// get this list (the caller checks). It loads only when opened.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { StrategySignal } from '../api/types'
import { formatDateTime } from '../lib/format'
import { EXPERIMENTAL, withoutScorePercent } from './beginner/cardText'
import { PageState } from './PageState'
import { SortTh, useSort } from './sort'
import { SCORE_NOTE, scoreLabel } from './scoreText'
import { Card, Tag, inr } from './ui'

const SIGNAL_WORD: Record<string, { label: string; tone: 'green' | 'amber' | 'red' | 'blue' }> = {
  BUY: { label: 'Buy signal', tone: 'green' },
  HOLD: { label: 'Hold', tone: 'blue' },
  SELL: { label: 'Sell signal', tone: 'red' },
  EXIT: { label: 'Exit signal', tone: 'red' },
}

const money = (n: number | null | undefined) => (n == null ? '—' : `₹${inr(n)}`)

/** What happened to a signal, in plain words. */
export function signalOutcome(s: StrategySignal): string {
  if (s.was_executed) return 'Acted on (paper)'
  if (s.rejection_reason) return `Not acted on: ${withoutScorePercent(s.rejection_reason)}`
  if (s.advisory_only) return 'Advice only'
  return 'Not acted on'
}

export function StrategySignals({ initiallyOpen = false }: { /** Tests only: draw it already open. */ initiallyOpen?: boolean } = {}) {
  const [open, setOpen] = useState(initiallyOpen)
  return (
    <Card
      title="Version 1 strategy signals"
      sub="What each of the older bot's strategies said in its latest scans. Read only: nothing here buys or sells."
    >
      <details data-feature="classic-strategy-signals" open={initiallyOpen || undefined} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary className="tm-link" style={{ cursor: 'pointer' }}>
          Show the signals
        </summary>
        <p className="tm-dim" style={{ fontSize: '0.76rem' }}>
          These are not the brain&apos;s ideas. The version 1 models ask a different question: does the price close
          2% or more higher within 5 days. {EXPERIMENTAL}. The model score is {SCORE_NOTE}.
        </p>
        {open && <SignalsBody />}
      </details>
    </Card>
  )
}

function SignalsBody() {
  const strategies = useQuery({ queryKey: ['strategies'], queryFn: api.strategies })
  const list = (strategies.data ?? []).filter((s) => s.strategy_type !== 'brain')
  const [picked, setPicked] = useState<number | null>(null)
  const chosen = list.find((s) => s.id === picked) ?? list.find((s) => s.is_active) ?? list[0]
  const signals = useQuery({
    queryKey: ['strategySignals', chosen?.id, 'discover'],
    queryFn: () => api.strategySignals(chosen!.id, 100),
    enabled: !!chosen,
  })

  if (strategies.isLoading) return <PageState kind="loading" what="the strategies" />
  if (strategies.isError) return <PageState kind="error" what="the strategies" error={strategies.error} onRetry={strategies.refetch} />
  if (!chosen) return <PageState kind="empty" reason="There is no version 1 strategy on this server." />

  const { sorted: rows, sorter } = useSort(signals.data ?? [], {
    stock: (s: StrategySignal) => s.tradingsymbol,
    signal: (s: StrategySignal) => s.signal_type,
    score: (s: StrategySignal) => s.confidence,
    price: (s: StrategySignal) => s.price,
    stop: (s: StrategySignal) => s.stop_loss,
    target: (s: StrategySignal) => s.take_profit,
    when: (s: StrategySignal) => s.generated_at,
  }, { key: null }, { stock: 'asc', signal: 'asc' })
  return (
    <div className="tm-grid" style={{ gap: '0.6rem', marginTop: '0.4rem' }}>
      <label className="tm-flex tm-wrap" style={{ gap: '0.5rem', alignItems: 'center' }}>
        <span className="tm-dim">Strategy</span>
        <select className="tm-select" value={chosen.id} onChange={(e) => setPicked(Number(e.target.value))}>
          {list.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.is_active ? '' : ' (switched off)'}
            </option>
          ))}
        </select>
      </label>
      {signals.isLoading && <PageState kind="loading" what="the signals" />}
      {signals.isError && <PageState kind="error" what="the signals" error={signals.error} onRetry={signals.refetch} />}
      {signals.data && rows.length === 0 && <PageState kind="empty" reason="This strategy has no signals yet." />}
      {rows.length > 0 && (
        <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Signals table, scroll sideways to see more">
          <table className="tm-table" data-testid="strategy-signals">
            <thead>
              <tr>
                <SortTh sorter={sorter} k="stock">Stock</SortTh>
                <SortTh sorter={sorter} k="signal">Signal</SortTh>
                <SortTh sorter={sorter} k="score" right>Model score</SortTh>
                <SortTh sorter={sorter} k="price" right>Price</SortTh>
                <SortTh sorter={sorter} k="stop" right>Stop loss</SortTh>
                <SortTh sorter={sorter} k="target" right>Target</SortTh>
                <SortTh sorter={sorter} k="when">When</SortTh>
                <th>What happened</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const w = SIGNAL_WORD[s.signal_type] ?? { label: s.signal_type, tone: 'blue' as const }
                return (
                  <tr key={s.id} data-signal={s.tradingsymbol}>
                    <td className="tm-strong">
                      <Link className="tm-link" to={`/trademind/stock/${encodeURIComponent(s.tradingsymbol)}`}>
                        {s.tradingsymbol}
                      </Link>
                    </td>
                    <td>
                      <Tag tone={w.tone}>{w.label}</Tag> <small className="tm-horizon-experimental">{EXPERIMENTAL}</small>
                    </td>
                    <td className="tm-right tm-num">{scoreLabel(s.confidence)}</td>
                    <td className="tm-right tm-num">{money(s.price)}</td>
                    <td className="tm-right tm-num">{money(s.stop_loss)}</td>
                    <td className="tm-right tm-num">{money(s.take_profit)}</td>
                    <td className="tm-dim">{formatDateTime(s.generated_at)}</td>
                    <td className="tm-dim">{signalOutcome(s)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
