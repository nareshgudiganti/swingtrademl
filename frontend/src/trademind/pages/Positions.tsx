import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { exitPlan, openPositions, pathData, position, reevalTriggers } from '../data'
import { ActionPill, Card, CheckItem, Icon, Seg, Tabs, Tag, inr, signed, toneClass } from '../ui'

const TABS = ['Position Overview', 'Expected vs Actual', 'Re-evaluation', 'Exit Strategy', 'Notes'] as const
type TabId = (typeof TABS)[number]

const LEVEL_TONE: Record<string, 'green' | 'amber' | 'red'> = { Normal: 'green', Watch: 'amber', High: 'red' }

function usePosition(symbol: string | undefined) {
  return useMemo(() => {
    const h = openPositions.find((p) => p.symbol === symbol) ?? openPositions[0]!
    if (h.symbol === position.symbol) return { ...position, name: h.name, status: h.status }
    const entry = h.avg
    return {
      symbol: h.symbol,
      name: h.name,
      status: h.status,
      entry,
      current: Math.round(entry * (1 + h.pnlPct / 100) * 10) / 10,
      pnlPct: h.pnlPct,
      sizePct: 5,
      target: Math.round(entry * 1.16),
      stop: Math.round(entry * 0.93),
      expectedR: 1.6,
      timeframe: '2-4 weeks',
      enteredOn: `${h.days} days ago`,
      daysHeld: h.days,
    }
  }, [symbol])
}

function PathChart({ entry, target, stop, height }: { entry: number; target: number; stop: number; height: number }) {
  const k = entry / position.entry
  const data = pathData.map((d) => ({
    t: d.t,
    expected: d.expected * k,
    actual: d.actual === null ? null : d.actual * k,
    band: [d.lower * k, d.upper * k] as [number, number],
  }))
  return (
    <div className="tm-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 10, right: 70, left: -6, bottom: 0 }}>
          <defs>
            <linearGradient id="tmBand" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4f8cff" stopOpacity={0.22} />
              <stop offset="100%" stopColor="#4f8cff" stopOpacity={0.04} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="t" tickLine={false} axisLine={false} interval={0} />
          <YAxis
            domain={[stop * 0.97, target * 1.06]}
            tickLine={false}
            axisLine={false}
            width={50}
            tickFormatter={(v: number) => inr(v, 0)}
          />
          <Tooltip
            content={({ active, payload }) =>
              active && payload?.length ? (
                <div className="tm-tooltip">
                  {payload
                    .filter((p) => p.dataKey !== 'band' && p.value != null)
                    .map((p) => (
                      <div key={String(p.dataKey)} style={{ color: p.color }}>
                        {p.dataKey === 'actual' ? 'Actual' : 'Expected'}: ₹{inr(Number(p.value))}
                      </div>
                    ))}
                </div>
              ) : null
            }
          />
          <Area dataKey="band" stroke="none" fill="url(#tmBand)" isAnimationActive={false} />
          <ReferenceLine y={target} stroke="#2ee68a" strokeDasharray="5 4" label={{ value: `Target ₹${inr(target, 0)}`, position: 'right', fill: '#2ee68a', fontSize: 10 }} />
          <ReferenceLine y={entry} stroke="#8f97c0" strokeDasharray="3 4" label={{ value: 'Entry', position: 'right', fill: '#8f97c0', fontSize: 10 }} />
          <ReferenceLine y={stop} stroke="#ff4d6a" strokeDasharray="5 4" label={{ value: `Stop ₹${inr(stop, 0)}`, position: 'right', fill: '#ff4d6a', fontSize: 10 }} />
          <Line dataKey="expected" stroke="#4f8cff" strokeDasharray="6 5" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line
            dataKey="actual"
            stroke="#2ee68a"
            strokeWidth={2.4}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
            style={{ filter: 'drop-shadow(0 0 5px #2ee68a)' }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

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

export default function Positions() {
  const { symbol } = useParams()
  const navigate = useNavigate()
  const p = usePosition(symbol)
  const [tab, setTab] = useState<TabId>('Position Overview')
  const [notes, setNotes] = useState(() => readNotes(p.symbol))
  const [reevaluated, setReevaluated] = useState(false)

  const details = (
    <Card title="Position Details">
      <dl className="tm-kv">
        <dt>Entry Price</dt>
        <dd>₹{inr(p.entry)}</dd>
        <dt>Current Price</dt>
        <dd>₹{inr(p.current)}</dd>
        <dt>P&amp;L</dt>
        <dd className={toneClass(p.pnlPct)}>{signed(p.pnlPct)}</dd>
        <dt>Position Size</dt>
        <dd>{p.sizePct}%</dd>
        <dt>Target Price</dt>
        <dd className="tm-pos">₹{inr(p.target, 0)}</dd>
        <dt>Stop Loss</dt>
        <dd className="tm-neg">₹{inr(p.stop, 0)}</dd>
        <dt title="Expected reward for every ₹1 risked">Expected R</dt>
        <dd className="tm-pos">+{p.expectedR}R</dd>
        <dt>Timeframe</dt>
        <dd style={{ color: 'var(--tm-violet)' }}>{p.timeframe}</dd>
      </dl>
    </Card>
  )

  const triggers = (
    <Card
      glow
      title="Re-evaluation Triggers"
      sub="The brain looks at this trade again if any of these happen"
      action={
        <button className="tm-btn" onClick={() => setReevaluated(true)}>
          Re-evaluate Now
        </button>
      }
    >
      <div className="tm-rows">
        {reevalTriggers.map((t) => (
          <div key={t.text} className="tm-row">
            <span className="tm-flex" style={{ gap: '0.55rem' }}>
              <span className="tm-check-icon" style={{ color: t.level === 'High' ? 'var(--tm-red)' : t.level === 'Watch' ? 'var(--tm-amber)' : 'var(--tm-green)', width: 18, height: 18 }}>
                <Icon.Alert />
              </span>
              {t.text}
            </span>
            <Tag tone={LEVEL_TONE[t.level] ?? 'amber'}>{t.level}</Tag>
          </div>
        ))}
      </div>
      {reevaluated && (
        <div className="tm-callout" style={{ marginTop: '0.7rem' }}>
          Re-checked just now: still <strong className="tm-pos">HOLD</strong> — nothing has changed enough to act.
          <span className="tm-faint"> (Demo — will call the brain once connected.)</span>
        </div>
      )}
    </Card>
  )

  return (
    <div className="tm-page">
      <div className="tm-toolbar">
        <Seg
          small
          active={p.symbol}
          onChange={(s) => {
            setNotes(readNotes(s))
            setReevaluated(false)
            navigate(`/trademind/positions/${s}`)
          }}
          options={openPositions.map((o) => ({
            id: o.symbol,
            label: (
              <>
                {o.name} <span className={toneClass(o.pnlPct)}>{signed(o.pnlPct)}</span>
              </>
            ),
          }))}
        />
      </div>

      <div className="tm-flex tm-wrap" style={{ marginBottom: '0.8rem', gap: '0.9rem' }}>
        <span className="tm-icon-badge" style={{ borderColor: 'rgba(79,140,255,.6)', color: 'var(--tm-blue)' }}>
          <Icon.Target />
        </span>
        <span style={{ fontSize: '1.25rem', fontWeight: 700 }}>{p.name.toUpperCase()}</span>
        <span className="tm-num" style={{ fontSize: '1.1rem', fontWeight: 600 }}>
          ₹{inr(p.current)}
        </span>
        <span className={`tm-num ${toneClass(p.pnlPct)}`} style={{ fontWeight: 600 }}>
          {signed(p.pnlPct)}
        </span>
        <ActionPill action="TRADE" />
        <Tag tone="violet">82% Confidence</Tag>
        <Tag tone="blue">Active Position</Tag>
        <Tag tone={p.status === 'Behind' || p.status === 'Watch' ? 'amber' : 'green'}>{p.status}</Tag>
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Position Overview' && (
        <div className="tm-grid">
          <div className="tm-grid tm-cols-3">
            <Card
              className="tm-span-2"
              title={
                <span className="tm-flex" style={{ gap: '1rem', fontWeight: 500, fontSize: '0.78rem' }}>
                  <span style={{ color: '#4f8cff' }}>◆ Expected Path</span>
                  <span style={{ color: '#2ee68a' }}>◆ Actual Price</span>
                </span>
              }
            >
              <PathChart entry={p.entry} target={p.target} stop={p.stop} height={290} />
            </Card>
            {details}
          </div>
          {triggers}
        </div>
      )}

      {tab === 'Expected vs Actual' && (
        <div className="tm-grid">
          <Card glow title="Is the trade on track?" sub="Blue dashed line = where the brain expected the price; shaded band = normal range">
            <PathChart entry={p.entry} target={p.target} stop={p.stop} height={340} />
          </Card>
          <div className="tm-grid tm-cols-4">
            <Card>
              <div className="tm-stat-label">Days held</div>
              <div className="tm-stat-value">{p.daysHeld}</div>
            </Card>
            <Card>
              <div className="tm-stat-label">Expected by now</div>
              <div className="tm-stat-value">+5.1%</div>
            </Card>
            <Card>
              <div className="tm-stat-label">Actually</div>
              <div className={`tm-stat-value ${toneClass(p.pnlPct)}`}>{signed(p.pnlPct)}</div>
            </Card>
            <Card>
              <div className="tm-stat-label">Verdict</div>
              <div className="tm-stat-value tm-pos">{p.status}</div>
            </Card>
          </div>
        </div>
      )}

      {tab === 'Re-evaluation' && <div className="tm-grid tm-cols-2">{triggers}{details}</div>}

      {tab === 'Exit Strategy' && (
        <div className="tm-grid tm-cols-3">
          <Card glow className="tm-span-2" title="How this trade will end" sub="The plan is fixed when the trade opens — no guessing later">
            <div className="tm-chain">
              {exitPlan.map((s, i) => (
                <div key={s.step} className={`tm-chain-step ${i === 3 ? 'tm-final' : ''}`}>
                  <span className="tm-chain-dot">{i === 3 ? <Icon.X /> : i === 4 ? <Icon.Clock /> : <Icon.Target />}</span>
                  <div>
                    <div className="tm-chain-title">
                      {s.step} · <span className="tm-num">{s.price}</span>
                    </div>
                    <div className="tm-chain-sub">{s.action}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          {details}
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
                writeNotes(p.symbol, e.target.value)
              }}
            />
          </Card>
          <Card title="Brain log">
            <CheckItem>Entered {p.enteredOn} at ₹{inr(p.entry)}</CheckItem>
            <CheckItem>Day 5: on track, kept HOLD</CheckItem>
            <CheckItem tone="warn">Day 11: sector dipped, moved to MONITOR</CheckItem>
            <CheckItem>Day 14: sector recovered, back to HOLD</CheckItem>
          </Card>
        </div>
      )}
    </div>
  )
}
