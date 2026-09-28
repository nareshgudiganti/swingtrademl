import type { DetailedPosition } from '../api/types'
import { ChevronRightIcon } from './icons'
import type { StockDetail } from './StockDetailModal'
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  pnlClass,
} from '../lib/format'

// One short, plain-English line per card. The model's own action_label is
// often a dense sentence ("Losing conviction (45% today) — alert already sent
// (original 5-day call has passed, day 6)"), which is the kind of jargon these
// pages exist to hide — so it reads as the smaller second line, with this as
// the headline.
const SHORT_REASON: Record<DetailedPosition['action_code'], string> = {
  exit: 'The bot wants to sell this one.',
  alert: 'An alert has already been sent about this one.',
  weak: 'Losing steam, but not a sell signal yet.',
  dip: 'Confidence has dipped since you bought it.',
  hold: 'Steady — no change.',
  bullish: 'Still bullish.',
}

/** Which book a flagged position came from. The distinction is not cosmetic:
 * the bot sells its own positions automatically, but shares bought by hand in
 * Zerodha it may only flag — so a card has to say which kind it is, or the
 * same red SELL badge would mean two different things. */
export type Book = 'yours' | 'bot'

const ACTION: Record<
  DetailedPosition['action_code'],
  { label: string; tone: 'sell' | 'watch' | 'neutral' }
> = {
  exit: { label: 'SELL', tone: 'sell' },
  alert: { label: 'REVIEW', tone: 'sell' },
  weak: { label: 'WATCH', tone: 'watch' },
  dip: { label: 'WATCH', tone: 'watch' },
  hold: { label: 'HOLD', tone: 'neutral' },
  bullish: { label: 'HOLD', tone: 'neutral' },
}

/** The popup payload for a position — one mapping, so a tap means the same
 * thing wherever a position is shown. */
export function detailForPosition(p: DetailedPosition): StockDetail {
  const action = ACTION[p.action_code]
  return {
    symbol: p.symbol,
    tone: action.tone === 'neutral' ? 'hold' : action.tone,
    actionLabel: action.label,
    price: p.current_price,
    entryPrice: p.entry_price,
    stopLoss: p.stop_loss,
    takeProfit: p.take_profit,
    confidence: p.last_confidence ?? p.entry_confidence,
    note: p.action_label,
  }
}

function Field({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="tech-field">
      <span className="tech-label">{label}</span>
      <span className={className ? `tech-value ${className}` : 'tech-value'}>{value}</span>
    </div>
  )
}

/** Everything about one flagged position, on the card itself.
 *
 * Replaces the summary line that used to name the stocks and stop there
 * ("SUZLON, IDEA, ACC have an exit or alert signal — open the stock for the
 * full read"). A list of tickers is not a read: deciding whether to sell
 * needs the price, what was paid, the stop, the money at stake and what the
 * model thinks now, and having to open nine stocks one at a time to collect
 * that is what made the alerts hard to act on. The popup still exists for the
 * chart; it is no longer where the basics live.
 */
export default function PositionAttentionCard({
  position,
  book,
  onOpen,
}: {
  position: DetailedPosition
  book: Book
  onOpen: () => void
}) {
  const action = ACTION[position.action_code]
  const stop = position.stop_loss
  // Signed so "below" reads as a fact rather than a distance: a position that
  // has already fallen through its stop is the whole reason this card exists.
  const stopGap = stop != null && position.current_price > 0
    ? (position.current_price - stop) / position.current_price
    : null
  const pastStop = stopGap != null && stopGap < 0

  return (
    <button
      className="action-card"
      style={{ width: '100%', textAlign: 'left', display: 'block' }}
      onClick={onOpen}
    >
      {/* The header stays [badge] [symbol] ....... [P&L] on a phone too: the
          book tag moved to its own line below because a long symbol used to
          squeeze the amount until the minus sign wrapped onto its own row. */}
      <div className="action-card-head">
        <div className="action-card-left">
          <span className={`pill-action ${action.tone}`}>{action.label}</span>
          <span className="action-card-symbol">{position.symbol}</span>
        </div>
        <span
          className={pnlClass(position.unrealized_pnl)}
          style={{ fontSize: '0.9rem', fontWeight: 700, whiteSpace: 'nowrap' }}
        >
          {formatCurrency(position.unrealized_pnl)}
        </span>
      </div>

      <div className="action-card-reason" style={{ color: 'var(--text)', fontWeight: 600 }}>
        {SHORT_REASON[position.action_code]}
      </div>
      <div className="action-card-reason" style={{ marginTop: '0.2rem' }}>
        {position.action_label}
      </div>
      <div className="action-card-reason" style={{ marginTop: '0.3rem' }}>
        {book === 'yours' ? (
          <>
            <strong>Your shares</strong> — bought by hand, so the bot will <strong>not</strong> sell
            them for you.
          </>
        ) : (
          <>
            <strong>Bot trade</strong> — it manages this one itself.
          </>
        )}
      </div>

      <div className="tech-grid attention-grid">
        <Field label="You hold" value={`${formatNumber(position.quantity)} shares`} />
        <Field label="You paid" value={formatCurrency(position.entry_price)} />
        <Field label="Price now" value={formatCurrency(position.current_price)} />
        <Field
          label="Gain / loss"
          value={formatSignedPercent(position.unrealized_pnl_pct, 1)}
          className={pnlClass(position.unrealized_pnl)}
        />
        {stop != null && (
          <Field
            label={pastStop ? 'Stop-loss (passed)' : 'Stop-loss'}
            value={
              stopGap == null
                ? formatCurrency(stop)
                : `${formatCurrency(stop)} · ${formatPercent(Math.abs(stopGap), 1)} ${pastStop ? 'below' : 'above'}`
            }
            className={pastStop ? 'neg' : undefined}
          />
        )}
        {position.take_profit != null && (
          <Field label="Target" value={formatCurrency(position.take_profit)} />
        )}
        <Field
          label="Held"
          value={
            position.horizon_days != null
              ? `${position.holding_days} of ${position.horizon_days} days`
              : `${position.holding_days} days`
          }
        />
        {(position.entry_confidence != null || position.last_confidence != null) && (
          <Field
            label="Confidence then → now"
            value={`${position.entry_confidence != null ? formatPercent(position.entry_confidence, 0) : '—'} → ${
              position.last_confidence != null ? formatPercent(position.last_confidence, 0) : '—'
            }`}
          />
        )}
        {position.day_pnl != null && (
          <Field
            label="Today"
            value={formatCurrency(position.day_pnl)}
            className={pnlClass(position.day_pnl)}
          />
        )}
      </div>

      <div className="strength-row">
        <span className="muted" style={{ fontSize: '0.8rem' }}>Tap for the price chart and full read</span>
        <ChevronRightIcon />
      </div>
    </button>
  )
}
