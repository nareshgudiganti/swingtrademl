// Pieces of the Open positions screen: the stop / half-profit / target progress bar, the "Act today" strip and the detail panel.
// Display only. Selling and "buy more" go through the same calls PaperPositions already makes.
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { DetailedPosition } from '../../api/types'
import ScoreTrail from '../ScoreTrail'
import { inr, signed, toneClass } from '../ui'
import { halfText, plan, stopText, targetText } from '../tradingRules'
import { priceUnavailableText } from '../../lib/priceUnavailable'
import { NO_PRICE_LEVEL, barPercent, levelFor, levels, priceAt, type Level } from './positionLevels'
import '../newlook-w4.css'

export const retPct = (p: DetailedPosition) => (p.unrealized_pnl_pct ?? 0) * 100
/** False when the server says nobody has priced the position, or sends no price or return (an older server sends no flag: priced). */
export const hasPrice = (p: DetailedPosition) =>
  p.has_price !== false && p.current_price != null && p.unrealized_pnl_pct != null
/** The return as text, or "Price unavailable" (with the last price time when known): a position nobody has priced is
 *  never shown as exactly flat (#486, #281). */
export const returnText = (p: DetailedPosition) => (hasPrice(p) ? signed(retPct(p)) : priceUnavailableText(p.price_as_of))
/** The price as ₹ text, or "Price unavailable". */
export const priceText = (p: DetailedPosition) =>
  hasPrice(p) ? `₹${inr(p.current_price ?? 0)}` : priceUnavailableText(p.price_as_of)
export const levelOf = (p: DetailedPosition): Level =>
  hasPrice(p) ? levelFor(retPct(p), p.suggestion === 'WATCH') : NO_PRICE_LEVEL

const rupee = (n: number, d = 2) => `${n < 0 ? '−' : ''}₹${inr(Math.abs(n), d)}`

export function LevelTag({ level }: { level: Level }) {
  return <span className={`op-tag op-tag-${level.tone}`}>{level.tag}</span>
}

/** One bar from the stop to the target, with a dot where the stock is now. */
export function PositionBar({ pct, big }: { pct: number; big?: boolean }) {
  const mark = (v: number) => `${barPercent(v)}%`
  const { stop: STOP_PCT, half: HALF_PCT, target: TARGET_PCT } = levels()
  return (
    <div
      className={`op-bar ${big ? 'op-bar-big' : ''}`}
      role="img"
      aria-label={`Return ${signed(pct)}. Stop at ${STOP_PCT}%, half-profit at +${HALF_PCT}%, target at +${TARGET_PCT}%.`}
    >
      <div className="op-bar-track">
        <span className="op-dot" style={{ left: mark(pct) }} />
      </div>
      <div className="op-bar-ticks">
        <span style={{ left: mark(STOP_PCT) }}>{stopText()}{big && <em>Stop</em>}</span>
        <span style={{ left: mark(0) }}>0%{big && <em>Entry</em>}</span>
        <span style={{ left: mark(HALF_PCT) }}>{halfText()}{big && <em>Half sell</em>}</span>
        <span style={{ left: mark(TARGET_PCT) }}>{targetText()}{big && <em>Target · {plan().days}-day plan</em>}</span>
      </div>
    </div>
  )
}

export function ActToday({ rows, onPick }: { rows: DetailedPosition[]; onPick: (id: number) => void }) {
  const items = rows.filter((p) => levelOf(p).act)
  return (
    <section className="op-act" aria-label="Act today">
      <div className="op-act-intro">
        <b>Act today</b>
        <span className="op-count">
          {items.length} {items.length === 1 ? 'stock' : 'stocks'}
        </span>
        <p className="tm-dim">Positions near a key level or needing action.</p>
      </div>
      {items.length === 0 ? (
        <p className="tm-dim op-act-none">Nothing needs action today. Every position is between its stop and its half-profit mark.</p>
      ) : (
        <div className="op-act-cards">
          {items.map((p) => {
            const l = levelOf(p)
            return (
              <button key={p.id} type="button" className={`op-act-card op-tone-${l.tone}`} onClick={() => onPick(p.id)}>
                <b>
                  {p.symbol} — {l.title}
                </b>
                <span className={`op-act-pct ${toneClass(p.unrealized_pnl ?? 0)}`}>{returnText(p)}</span>
                <span>{l.advice}</span>
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}

export function DetailPanel({
  p,
  trailOpen,
  onTrail,
  onClose,
  children,
}: {
  p: DetailedPosition
  trailOpen: boolean
  onTrail: () => void
  /** Hides the panel so the table shows the full page. */
  onClose?: () => void
  /** Buy more / sell controls, supplied by the page. */
  children: ReactNode
}) {
  const l = levelOf(p)
  const lv = levels()
  const half = priceAt(p.entry_price, lv.half)
  const target = priceAt(p.entry_price, lv.target)
  const stop = priceAt(p.entry_price, lv.stop)
  return (
    <aside className="op-panel" aria-label={`${p.symbol} detail`}>
      <div className="op-panel-head">
        <div>
          <b className="op-panel-name">{p.name ?? p.symbol}</b> <span className="tm-dim">({p.symbol})</span>
        </div>
        <span className="tm-flex" style={{ gap: '0.5rem', alignItems: 'center' }}>
          <LevelTag level={l} />
          {onClose && (
            <button type="button" className="op-panel-close" onClick={onClose} aria-label="Close panel">
              ✕
            </button>
          )}
        </span>
      </div>
      <div className="tm-dim">Current return</div>
      <div className={`op-panel-ret ${toneClass(p.unrealized_pnl ?? 0)}`}>
        {hasPrice(p) ? (
          <>
            {signed(retPct(p))} <small>({rupee(p.unrealized_pnl ?? 0, 0)})</small>
          </>
        ) : (
          returnText(p)
        )}
      </div>
      {hasPrice(p) && <PositionBar pct={retPct(p)} big />}
      <div className="op-levels">
        <dl>
          <dt>Entry price</dt>
          <dd>₹{inr(p.entry_price)}</dd>
          <dt>Current price</dt>
          <dd>{priceText(p)}</dd>
          <dt>Quantity</dt>
          <dd>{p.quantity}</dd>
          <dt>Invested</dt>
          <dd>₹{inr(p.invested, 0)}</dd>
        </dl>
        <dl>
          <dt>Stop loss</dt>
          <dd className="tm-neg">₹{inr(stop)} ({stopText()})</dd>
          <dt>Half-profit</dt>
          <dd className="tm-pos">₹{inr(half)} ({halfText()})</dd>
          <dt>Target</dt>
          <dd className="tm-pos">₹{inr(target)} ({targetText()}, {plan().days}-day plan)</dd>
        </dl>
      </div>
      <p className={`op-suggest op-tone-${l.tone}`}>
        <b>Suggestion:</b> {l.advice}
        {p.suggestion_reason ? ` ${p.suggestion_reason}` : ''}
      </p>
      <div className="op-actions">
        <button type="button" className="tm-btn" onClick={onTrail} aria-expanded={trailOpen}>
          Score trail
        </button>
        <Link className="tm-btn" to={`/trademind/ai/${p.symbol}`}>
          AI analysis
        </Link>
        <Link className="tm-btn" to={`/trademind/stock/${p.symbol}`}>
          Stock page
        </Link>
      </div>
      {trailOpen && <ScoreTrail p={p} />}
      {children}
    </aside>
  )
}
