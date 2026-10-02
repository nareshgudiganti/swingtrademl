// Shared TradeMind building blocks: glowing cards, ring gauges, donuts,
// area charts, candlesticks and the brain artwork.

import { useId, type ReactNode } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import clsx from 'clsx'

import type { Action, CandleBar, Point } from './data'

// ------------------------------------------------------------- formatting --

export const inr = (n: number, digits = 2) =>
  n.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export const signed = (n: number, digits = 1, suffix = '%') =>
  `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(digits)}${suffix}`

export const toneClass = (n: number) => (n > 0 ? 'tm-pos' : n < 0 ? 'tm-neg' : 'tm-dim')

// ------------------------------------------------------------------ icons --

type IconProps = { size?: number }
const svgProps = (size = 16) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
})

export const Icon = {
  Check: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  ),
  X: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  ),
  Alert: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M12 8v5M12 16.5v.5" />
      <circle cx="12" cy="12" r="9" />
    </svg>
  ),
  Minus: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M7 12h10" />
    </svg>
  ),
  User: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" />
    </svg>
  ),
  Search: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </svg>
  ),
  Pulse: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M3 12h4l2-6 4 12 2-6h6" />
    </svg>
  ),
  Target: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1" />
    </svg>
  ),
  Layers: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M12 3l9 5-9 5-9-5 9-5z" />
      <path d="M3 13l9 5 9-5" />
    </svg>
  ),
  Chart: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>
  ),
  Shield: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z" />
      <path d="M8.5 12l2.5 2.5 4.5-5" />
    </svg>
  ),
  Spark: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M18 6l-2.5 2.5M8.5 15.5L6 18" />
    </svg>
  ),
  Book: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2V5z" />
      <path d="M4 19a2 2 0 012-2h13" />
    </svg>
  ),
  Clock: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  ),
  Bolt: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" />
    </svg>
  ),
  Back: ({ size }: IconProps) => (
    <svg {...svgProps(size)}>
      <path d="M15 18l-6-6 6-6" />
    </svg>
  ),
}

// ------------------------------------------------------------------ cards --

export function Card({
  title,
  sub,
  action,
  glow,
  className,
  children,
}: {
  title?: ReactNode
  sub?: ReactNode
  action?: ReactNode
  glow?: boolean | 'green'
  className?: string
  children?: ReactNode
}) {
  return (
    <section
      className={clsx('tm-card', glow === true && 'tm-glow', glow === 'green' && 'tm-glow-green', className)}
    >
      {(title || action) && (
        <header className="tm-card-head">
          <div>
            {title && <h3 className="tm-card-title">{title}</h3>}
            {sub && <div className="tm-card-sub">{sub}</div>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function PageHead({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="tm-page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {right}
    </div>
  )
}

/** A muted card for anything the brain doesn't (yet) answer — never fill
 * the gap with a sample number. */
export function NotConnected({ what, reason }: { what: string; reason?: string }) {
  return (
    <Card title={what}>
      <p className="tm-dim">{reason ?? 'Not connected yet.'}</p>
    </Card>
  )
}

/** Shown wherever a screen would otherwise ask the brain for something and
 * every brain endpoint is 404ing — BRAIN_ENABLED is off on this server. */
export function BrainOff() {
  return (
    <Card title="Brain off">
      <p className="tm-dim">The brain is switched off on this server.</p>
    </Card>
  )
}

const ACTION_HINT: Record<Action, string> = {
  TRADE: 'Worth buying now, at the suggested size',
  WATCH: 'Interesting — wait for a better moment',
  WAIT: 'Nothing to do yet',
  AVOID: 'Stay away for now',
}

export function ActionPill({ action }: { action: Action }) {
  return (
    <span className={`tm-pill tm-pill-${action.toLowerCase()}`} title={ACTION_HINT[action]}>
      {action}
    </span>
  )
}

export function Tag({ tone, children }: { tone: 'green' | 'amber' | 'red' | 'blue' | 'violet'; children: ReactNode }) {
  return <span className={`tm-tag tm-tag-${tone}`}>{children}</span>
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: readonly T[]
  active: T
  onChange: (t: T) => void
}) {
  return (
    <div className="tm-tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t} role="tab" aria-selected={t === active} className={clsx(t === active && 'active')} onClick={() => onChange(t)}>
          {t}
        </button>
      ))}
    </div>
  )
}

export function Seg<T extends string>({
  options,
  active,
  onChange,
  small,
}: {
  options: readonly { id: T; label: ReactNode }[]
  active: T
  onChange: (t: T) => void
  small?: boolean
}) {
  return (
    <div className={clsx('tm-seg', small && 'tm-seg-sm')}>
      {options.map((o) => (
        <button key={o.id} className={clsx(o.id === active && 'active')} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function CheckItem({
  tone = 'pos',
  children,
}: {
  tone?: 'pos' | 'neg' | 'warn' | 'neutral'
  children: ReactNode
}) {
  const color =
    tone === 'pos' ? 'var(--tm-green)' : tone === 'neg' ? 'var(--tm-red)' : tone === 'warn' ? 'var(--tm-amber)' : 'var(--tm-blue)'
  return (
    <div className="tm-check">
      <span className="tm-check-icon" style={{ color }}>
        {tone === 'neg' ? <Icon.X /> : tone === 'warn' ? <Icon.Alert /> : tone === 'neutral' ? <Icon.Minus /> : <Icon.Check />}
      </span>
      <span style={{ paddingTop: 1 }}>{children}</span>
    </div>
  )
}

// ------------------------------------------------------------ ring gauge --

const RING_COLORS: Record<string, [string, string]> = {
  green: ['#16c172', '#4dffb0'],
  blue: ['#2563eb', '#33d6ff'],
  violet: ['#7c3aed', '#c084fc'],
  amber: ['#f59e0b', '#ffd27a'],
  red: ['#e11d48', '#ff7a90'],
  rainbow: ['#2ee68a', '#33d6ff'],
}

export function Ring({
  value,
  max = 100,
  size = 96,
  stroke = 8,
  color = 'green',
  center,
  label,
  valueSize,
}: {
  value: number
  max?: number
  size?: number
  stroke?: number
  color?: keyof typeof RING_COLORS
  center?: ReactNode
  label?: ReactNode
  valueSize?: number
}) {
  const id = useId().replace(/:/g, '')
  const r = (size - stroke) / 2 - 2
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(1, value / max))
  const [a, b] = RING_COLORS[color] ?? RING_COLORS.green!
  return (
    <div className="tm-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ filter: `drop-shadow(0 0 6px ${b}88)` }}>
        <defs>
          <linearGradient id={`rg${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={a} />
            <stop offset="100%" stopColor={b} />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(139,124,255,0.12)" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={`url(#rg${id})`}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={`${c * pct} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="tm-ring-center">
        {center ?? (
          <span className="tm-ring-value" style={{ fontSize: valueSize ?? size * 0.26 }}>
            {value}
          </span>
        )}
        {label && <span className="tm-ring-label">{label}</span>}
      </div>
    </div>
  )
}

// ----------------------------------------------------------------- donut --

export function Donut({
  segments,
  size = 150,
  stroke = 20,
  center,
}: {
  segments: { pct: number; color: string; name?: string }[]
  size?: number
  stroke?: number
  center?: ReactNode
}) {
  const r = (size - stroke) / 2 - 3
  const c = 2 * Math.PI * r
  const total = segments.reduce((s, x) => s + x.pct, 0) || 1
  const gap = 2.5
  let offset = 0
  return (
    <div className="tm-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(139,124,255,0.08)" strokeWidth={stroke} fill="none" />
        {segments.map((s) => {
          const len = (s.pct / total) * c
          const el = (
            <circle
              key={s.color + s.pct + (s.name ?? '')}
              cx={size / 2}
              cy={size / 2}
              r={r}
              stroke={s.color}
              strokeWidth={stroke}
              fill="none"
              strokeDasharray={`${Math.max(len - gap, 0)} ${c}`}
              strokeDashoffset={-offset}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
              style={{ filter: `drop-shadow(0 0 5px ${s.color}aa)` }}
            >
              {s.name && <title>{`${s.name}: ${s.pct}%`}</title>}
            </circle>
          )
          offset += len
          return el
        })}
      </svg>
      {center && <div className="tm-ring-center">{center}</div>}
    </div>
  )
}

// ------------------------------------------------------------- area chart --

export function GlowArea({
  data,
  color = '#2ee68a',
  height = 140,
  axes = false,
  domain,
  formatter = (v: number) => inr(v, 0),
  extra,
}: {
  data: (Point | Record<string, unknown>)[]
  color?: string
  height?: number
  axes?: boolean
  domain?: [number | 'auto' | 'dataMin' | 'dataMax', number | 'auto' | 'dataMin' | 'dataMax']
  formatter?: (v: number) => string
  extra?: ReactNode
}) {
  const id = useId().replace(/:/g, '')
  return (
    <div className="tm-chart tm-chart-glow" style={{ height, color }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 6, right: axes ? 4 : 0, left: axes ? -8 : 0, bottom: 0 }}>
          <defs>
            <linearGradient id={`ga${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.45} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          {axes && <CartesianGrid vertical={false} />}
          <XAxis dataKey="t" hide={!axes} tickLine={false} axisLine={false} interval={0} />
          <YAxis
            hide={!axes}
            domain={domain ?? ['dataMin', 'dataMax']}
            tickLine={false}
            axisLine={false}
            width={48}
            tickFormatter={(v: number) => formatter(v)}
          />
          <Tooltip
            cursor={{ stroke: 'rgba(160,140,255,0.35)' }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <div className="tm-tooltip">{formatter(Number(payload[0]?.value))}</div>
              ) : null
            }
          />
          {extra}
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#ga${id})`} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// --------------------------------------------------------------- candles --

export function Candles({
  bars,
  height = 300,
  target,
  stop,
}: {
  bars: CandleBar[]
  height?: number
  target?: number
  stop?: number
}) {
  const W = 760
  const H = height
  const padR = 52
  const padB = 22
  const volH = H * 0.16
  const priceH = H - padB - volH - 6
  const hi = Math.max(...bars.map((b) => b.h), target ?? 0)
  const lo = Math.min(...bars.map((b) => b.l), stop ?? Infinity)
  const span = hi - lo || 1
  const y = (p: number) => 6 + ((hi - p) / span) * (priceH - 12)
  const step = (W - padR) / bars.length
  const bw = Math.max(step * 0.62, 1.5)
  const maxVol = Math.max(...bars.map((b) => b.vol))
  const ticks = Array.from({ length: 5 }, (_, i) => lo + (span * i) / 4)
  const id = useId().replace(/:/g, '')

  return (
    <svg className="tm-candles" viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
      <defs>
        <filter id={`cg${id}`}>
          <feGaussianBlur stdDeviation="1.4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={0} x2={W - padR} y1={y(t)} y2={y(t)} stroke="rgba(118,110,255,0.08)" />
          <text x={W - padR + 6} y={y(t) + 3}>
            {inr(t, 0)}
          </text>
        </g>
      ))}
      {target && (
        <g>
          <line x1={0} x2={W - padR} y1={y(target)} y2={y(target)} stroke="#2ee68a" strokeDasharray="5 4" opacity={0.8} />
          <text x={4} y={y(target) + 12} style={{ fill: '#2ee68a' }}>
            Target ₹{inr(target, 0)}
          </text>
        </g>
      )}
      {stop && (
        <g>
          <line x1={0} x2={W - padR} y1={y(stop)} y2={y(stop)} stroke="#ff4d6a" strokeDasharray="5 4" opacity={0.8} />
          <text x={4} y={y(stop) + 12} style={{ fill: '#ff4d6a' }}>
            Stop ₹{inr(stop, 0)}
          </text>
        </g>
      )}
      <g filter={`url(#cg${id})`}>
        {bars.map((b, i) => {
          const x = i * step + step / 2
          const up = b.c >= b.o
          const col = up ? '#2ee68a' : '#ff4d6a'
          const top = y(Math.max(b.o, b.c))
          const bot = y(Math.min(b.o, b.c))
          return (
            <g key={i}>
              <line x1={x} x2={x} y1={y(b.h)} y2={y(b.l)} stroke={col} strokeWidth={1} />
              <rect x={x - bw / 2} y={top} width={bw} height={Math.max(bot - top, 1)} fill={col} />
              <rect
                x={x - bw / 2}
                y={H - padB - (b.vol / maxVol) * volH}
                width={bw}
                height={(b.vol / maxVol) * volH}
                fill={col}
                opacity={0.35}
              />
            </g>
          )
        })}
      </g>
      {bars.map((b, i) =>
        i % Math.ceil(bars.length / 6) === 0 ? (
          <text key={`l${i}`} x={i * step + step / 2} y={H - 6} textAnchor="middle">
            {b.t}
          </text>
        ) : null,
      )}
    </svg>
  )
}

// ---------------------------------------------------------------- brain --

// A stylised glowing brain: two hemispheres of folds plus a neural network of
// lit nodes. Pure SVG so it stays sharp at any size.
export function BrainArt() {
  const id = useId().replace(/:/g, '')
  const nodes: [number, number][] = [
    [62, 52], [88, 36], [118, 30], [92, 70], [60, 92], [84, 108], [118, 96], [112, 62],
    [148, 36], [178, 52], [176, 92], [150, 108], [140, 70], [196, 76], [44, 74], [128, 122],
  ]
  const links: [number, number][] = [
    [0, 1], [1, 2], [1, 3], [3, 4], [4, 5], [5, 6], [3, 7], [7, 2], [7, 6], [0, 14], [14, 4],
    [2, 8], [8, 9], [9, 13], [13, 10], [10, 11], [11, 15], [6, 15], [12, 8], [12, 10], [12, 7], [12, 11],
  ]
  return (
    <svg viewBox="0 0 240 150" aria-hidden="true">
      <defs>
        <radialGradient id={`bf${id}`} cx="50%" cy="45%" r="60%">
          <stop offset="0%" stopColor="#4fa3ff" stopOpacity="0.55" />
          <stop offset="60%" stopColor="#5b3fd6" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#1a1050" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`bs${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#7dd3fc" />
          <stop offset="55%" stopColor="#818cf8" />
          <stop offset="100%" stopColor="#c084fc" />
        </linearGradient>
      </defs>
      <ellipse cx="120" cy="76" rx="112" ry="70" fill={`url(#bf${id})`} />
      {/* outline: left + right hemisphere */}
      <path
        d="M118 20c-14-8-34-6-44 4-14-2-28 8-30 22-12 6-18 20-12 34-6 12 0 28 12 32 2 14 18 22 32 18 10 10 28 10 40 0"
        fill="rgba(60,90,220,0.12)"
        stroke={`url(#bs${id})`}
        strokeWidth="2.2"
      />
      <path
        d="M122 20c14-8 34-6 44 4 14-2 28 8 30 22 12 6 18 20 12 34 6 12 0 28-12 32-2 14-18 22-32 18-10 10-28 10-40 0"
        fill="rgba(110,70,230,0.12)"
        stroke={`url(#bs${id})`}
        strokeWidth="2.2"
      />
      <path d="M120 20v110" stroke="#a5b4fc" strokeOpacity="0.5" strokeWidth="1.4" />
      {/* folds */}
      <g stroke={`url(#bs${id})`} strokeOpacity="0.75" strokeWidth="1.4" fill="none" strokeLinecap="round">
        <path d="M74 24c6 10 2 18-8 22" />
        <path d="M46 52c10 2 16 10 14 20" />
        <path d="M36 84c12-4 22 2 26 12" />
        <path d="M58 118c4-10 14-14 24-10" />
        <path d="M98 128c-4-10 0-20 10-24" />
        <path d="M100 40c-8 8-6 20 4 24" />
        <path d="M80 80c8-6 20-4 24 6" />
        <path d="M166 24c-6 10-2 18 8 22" />
        <path d="M194 52c-10 2-16 10-14 20" />
        <path d="M204 84c-12-4-22 2-26 12" />
        <path d="M182 118c-4-10-14-14-24-10" />
        <path d="M142 128c4-10 0-20-10-24" />
        <path d="M140 40c8 8 6 20-4 24" />
        <path d="M160 80c-8-6-20-4-24 6" />
      </g>
      {/* neural network */}
      <g stroke="#7dd3fc" strokeOpacity="0.55" strokeWidth="0.9">
        {links.map(([a, b]) => (
          <line key={`${a}-${b}`} x1={nodes[a]![0]} y1={nodes[a]![1]} x2={nodes[b]![0]} y2={nodes[b]![1]} />
        ))}
      </g>
      {nodes.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 2.6 : 1.8} fill={i % 2 ? '#e0f2fe' : '#c4b5fd'}>
          <animate attributeName="opacity" values="1;0.35;1" dur={`${2 + (i % 5) * 0.6}s`} repeatCount="indefinite" />
        </circle>
      ))}
    </svg>
  )
}

// ------------------------------------------------------------- bar rows --

export function HBar({
  label,
  value,
  max,
  tone,
  right,
  labelWidth,
}: {
  label: ReactNode
  value: number
  max: number
  tone: 'up' | 'down' | 'flat' | 'violet'
  right?: ReactNode
  labelWidth?: number
}) {
  return (
    <div className="tm-hbar" style={labelWidth ? { gridTemplateColumns: `${labelWidth}px 1fr 40px` } : undefined}>
      <span className="tm-dim">{label}</span>
      <div className="tm-hbar-track">
        <div className={`tm-hbar-fill tm-${tone}`} style={{ width: `${Math.min(100, (Math.abs(value) / max) * 100)}%` }} />
      </div>
      <span className={clsx('tm-right tm-num', tone === 'up' ? 'tm-pos' : tone === 'down' ? 'tm-neg' : '')}>{right}</span>
    </div>
  )
}

export function Meter({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="tm-meter">
      <span style={{ width: `${Math.min(100, pct)}%`, background: color, boxShadow: `0 0 8px ${color}` }} />
    </div>
  )
}

export function StockLogo({ symbol }: { symbol: string }) {
  return <span className="tm-stock-logo">{symbol.replace(/[^A-Z]/g, '').slice(0, 2)}</span>
}
