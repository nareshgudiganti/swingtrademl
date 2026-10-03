import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { BrainDecision, DetailedPosition } from '../../api/types'
import { formatDate } from '../../lib/format'
import { holdingsFrom, useBrainStatus, useLatestRun, useTrack } from '../live'
import { BrainOff, Card, CheckItem, Icon, Seg, Tabs, Tag, inr, signed, toneClass } from '../ui'
import { PositionBand } from '../PositionBand'

// Same private copy as every other TradeMind screen (see Home.tsx) — the
// owner's overrule, if any, otherwise the brain's own word.
function finalWord(d: BrainDecision): string {
  return d.overruled_word ?? d.word
}

const HOLDING_TONE: Record<string, 'green' | 'blue' | 'amber' | 'red'> = {
  HOLD: 'green',
  MONITOR: 'blue',
  REDUCE: 'amber',
  EXIT: 'red',
}

const REASON_TONE: Record<string, 'pos' | 'neg' | 'warn' | 'neutral'> = {
  HOLD: 'pos',
  MONITOR: 'warn',
  REDUCE: 'warn',
  EXIT: 'neg',
}

const TABS = ['Position Overview', 'Re-evaluation & Exit', 'Notes'] as const
type TabId = (typeof TABS)[number]

const NOTES_KEY = 'tm_position_notes'

function readNotes(symbol: string) {
  try {
    return (JSON.parse(localStorage.getItem(NOTES_KEY) ?? '{}') as Record<string, string>)[symbol] ?? ''
  } catch {
    return ''
  }
}

function writeNotes(symbol: string, text: string) {
  try {
    const all = JSON.parse(localStorage.getItem(NOTES_KEY) ?? '{}') as Record<string, string>
    all[symbol] = text
    localStorage.setItem(NOTES_KEY, JSON.stringify(all))
  } catch {
    /* storage blocked — notes simply don't persist */
  }
}

/** The fixed plan every TRADE is held to, applied to this position's real
 * entry price and real decision levels — never a guessed number. */
function ExitPlan({ decision, pos }: { decision: BrainDecision; pos: DetailedPosition | undefined }) {
  const entry = pos?.entry_price ?? null
  const steps = [
    {
      step: 'First target',
      price: entry != null ? `₹${inr(entry * 1.05, 0)} (rule: entry +5%)` : 'Rule: entry +5%',
      action: 'Sell half, lock in profit',
      icon: <Icon.Target />,
    },
    {
      step: 'Protect the rest',
      price: entry != null ? `Move stop to ₹${inr(entry, 0)}` : 'Move stop to your entry price',
      action: 'Worst case: break even',
      icon: <Icon.Shield />,
    },
    {
      step: 'Final target',
      price: decision.target != null ? `₹${inr(decision.target, 0)}` : '—',
      action: 'Sell the rest',
      icon: <Icon.Target />,
    },
    {
      step: 'Stop loss',
      price: decision.stop != null ? `₹${inr(decision.stop, 0)}` : '—',
      action: 'Sell everything, no questions',
      icon: <Icon.X />,
    },
    {
      step: 'Time stop',
      price: pos?.entry_at
        ? `by ${formatDate(new Date(new Date(pos.entry_at).getTime() + 30 * 86_400_000).toISOString())}`
        : 'Rule: 30 calendar days after entry',
      action: 'Sell if nothing has happened by then',
      icon: <Icon.Clock />,
    },
  ]
  return (
    <div className="tm-chain">
      {steps.map((s, i) => (
        <div key={s.step} className={`tm-chain-step ${i === 3 ? 'tm-final' : ''}`}>
          <span className="tm-chain-dot">{s.icon}</span>
          <div>
            <div className="tm-chain-title">
              {s.step} · <span className="tm-num">{s.price}</span>
            </div>
            <div className="tm-chain-sub">{s.action}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function Positions() {
  const { symbol: urlSymbol } = useParams()
  const navigate = useNavigate()
  const status = useBrainStatus()
  const latest = useLatestRun()
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })

  const run = latest.data
  const holdings = run ? holdingsFrom(run) : []
  const selected = holdings.find((h) => h.symbol === urlSymbol) ?? holdings[0]
  const track = useTrack(selected?.symbol)

  const [tab, setTab] = useState<TabId>('Position Overview')
  const [notes, setNotes] = useState('')

  useEffect(() => {
    if (selected) setNotes(readNotes(selected.symbol))
  }, [selected?.symbol])

  if (status === 'off') return <div className="tm-page"><BrainOff /></div>

  if (status === 'loading') {
    return (
      <div className="tm-page">
        <p className="tm-dim">Connecting to the brain…</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tm-page">
        <Card title="Could not reach the brain">
          <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  if (status === 'no-run') {
    return (
      <div className="tm-page">
        <Card title="No run yet">
          <p className="tm-dim">The brain has not run yet.</p>
        </Card>
      </div>
    )
  }

  if (!selected) {
    return (
      <div className="tm-page">
        <Card title="No positions">
          <p className="tm-dim">You are not holding anything right now.</p>
        </Card>
      </div>
    )
  }

  const pos = (positions.data ?? []).find((p) => p.symbol === selected.symbol)

  const details = (
    <Card title="Position Details">
      {positions.isLoading && <p className="tm-dim">Loading live price…</p>}
      {positions.isError && <p className="tm-dim">Live price is not available right now.</p>}
      {!positions.isLoading && !positions.isError && (
        <dl className="tm-kv">
          <dt>Entry Price</dt>
          <dd>{pos ? `₹${inr(pos.entry_price)}` : '—'}</dd>
          <dt>Current Price</dt>
          <dd>{pos ? `₹${inr(pos.current_price)}` : '—'}</dd>
          <dt>P&amp;L</dt>
          <dd className={pos ? toneClass(pos.unrealized_pnl_pct) : undefined}>
            {pos ? signed(pos.unrealized_pnl_pct * 100) : '—'}
          </dd>
          <dt>Quantity</dt>
          <dd>{pos ? pos.quantity : '—'}</dd>
          <dt>Target Price</dt>
          <dd className="tm-pos">{selected.target != null ? `₹${inr(selected.target, 0)}` : '—'}</dd>
          <dt>Stop Loss</dt>
          <dd className="tm-neg">{selected.stop != null ? `₹${inr(selected.stop, 0)}` : '—'}</dd>
          <dt>Horizon</dt>
          <dd style={{ color: 'var(--tm-violet)' }}>up to {selected.horizon_days} trading days</dd>
        </dl>
      )}
    </Card>
  )

  const triggers = (
    <Card glow title="What the Brain Is Watching" sub="The reasons behind today's word — re-checked on the brain's next run">
      {selected.reasons.length === 0 ? (
        <p className="tm-dim">No specific reasons recorded for this decision.</p>
      ) : (
        <div className="tm-rows">
          {selected.reasons.map((r, i) => (
            <CheckItem key={i} tone={REASON_TONE[finalWord(selected)] ?? 'neutral'}>
              {r}
            </CheckItem>
          ))}
        </div>
      )}
    </Card>
  )

  return (
    <div className="tm-page">
      <div className="tm-toolbar">
        <Seg
          small
          active={selected.symbol}
          onChange={(s) => navigate(`/trademind/positions/${s}`)}
          options={holdings.map((h) => ({
            id: h.symbol,
            label: <>{h.symbol} <Tag tone={HOLDING_TONE[finalWord(h)] ?? 'blue'}>{finalWord(h)}</Tag></>,
          }))}
        />
      </div>

      <div className="tm-flex tm-wrap" style={{ marginBottom: '0.8rem', gap: '0.9rem' }}>
        <span className="tm-icon-badge" style={{ borderColor: 'rgba(79,140,255,.6)', color: 'var(--tm-blue)' }}>
          <Icon.Target />
        </span>
        <span style={{ fontSize: '1.25rem', fontWeight: 700 }}>{selected.symbol}</span>
        {pos && (
          <>
            <span className="tm-num" style={{ fontSize: '1.1rem', fontWeight: 600 }}>
              ₹{inr(pos.current_price)}
            </span>
            <span className={`tm-num ${toneClass(pos.unrealized_pnl_pct)}`} style={{ fontWeight: 600 }}>
              {signed(pos.unrealized_pnl_pct * 100)}
            </span>
          </>
        )}
        <Tag tone={HOLDING_TONE[finalWord(selected)] ?? 'blue'}>{finalWord(selected)}</Tag>
        {selected.confidence != null && <Tag tone="violet">{Math.round(selected.confidence * 100)} model score</Tag>}
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Position Overview' && (
        <div className="tm-grid">
          <div className="tm-grid tm-cols-3">
            <Card className="tm-span-2" title="This Trade vs. Similar Past Trades">
              {track.isLoading && <p className="tm-dim">Loading…</p>}
              {track.isError && <p className="tm-dim">Not available right now.</p>}
              {track.data && (
                <PositionBand track={track.data} entry={pos?.entry_price} target={selected.target} stop={selected.stop} />
              )}
            </Card>
            {details}
          </div>
          {triggers}
        </div>
      )}

      {tab === 'Re-evaluation & Exit' && (
        <div className="tm-grid tm-cols-3">
          <Card glow className="tm-span-2" title="How this trade will end" sub="The plan is fixed when the trade opens — no guessing later">
            <ExitPlan decision={selected} pos={pos} />
          </Card>
          {details}
          <div className="tm-span-3">{triggers}</div>
        </div>
      )}

      {tab === 'Notes' && (
        <div className="tm-grid tm-cols-3">
          <Card className="tm-span-2" title="Your notes" sub="Saved in this browser only">
            <textarea
              className="tm-input"
              style={{ width: '100%', minHeight: 220, resize: 'vertical' }}
              placeholder="Why did you take this trade? Anything to remember?"
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value)
                writeNotes(selected.symbol, e.target.value)
              }}
            />
          </Card>
          {details}
        </div>
      )}
    </div>
  )
}
