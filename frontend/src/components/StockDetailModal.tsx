import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { ErrorBox, Loading } from './Loading'
import Modal from './Modal'
import PricePerformance from './PricePerformance'
import { formatCurrency, formatDateTime, formatPercent } from '../lib/format'

export interface StockDetail {
  symbol: string
  tone: 'buy' | 'sell' | 'watch' | 'hold'
  actionLabel: string
  price: number
  entryPrice?: number | null
  stopLoss?: number | null
  takeProfit?: number | null
  confidence?: number | null
  note?: string | null
  // When this call was last confirmed — the whole point of showing it is
  // "does this signal still reflect today's price, or was it from a scan a
  // day or two ago" before you act on it.
  asOf?: string | null
}

/** The popup a click on any stock card opens — everything needed to decide
 * without leaving the page: current price, your entry (if you hold it), the
 * stop/target, the model's confidence, and the plain-language reason already
 * on the card, plus the price chart for context. One shared shape so a click
 * means the same thing on Dashboard, Portfolio, or anywhere else a stock is
 * shown as a card. */
export default function StockDetailModal({ detail, onClose }: { detail: StockDetail; onClose: () => void }) {
  const candles = useQuery({
    queryKey: ['dailyCandles', detail.symbol],
    queryFn: () => api.candles(detail.symbol, 90),
  })

  return (
    <Modal onClose={onClose}>
      <div className="detail-panel">
        <div className="detail-head">
          <div>
            <h2 className="detail-symbol" style={{ marginTop: 0 }}>{detail.symbol}</h2>
            {detail.asOf && (
              <div className="detail-sub" style={{ marginTop: '0.15rem' }}>
                Confirmed {formatDateTime(detail.asOf)}
              </div>
            )}
          </div>
          <span className={`badge badge-lg badge-${detail.tone}`}>{detail.actionLabel}</span>
        </div>
        {detail.note && <div className="detail-sub" style={{ marginTop: '0.35rem' }}>{detail.note}</div>}

        <div className="detail-stat-row" style={{ marginTop: '0.9rem' }}>
          <div className="detail-stat">
            <div className="tech-label">Current price</div>
            <div className="detail-stat-value">{formatCurrency(detail.price)}</div>
          </div>
          {detail.entryPrice != null && (
            <div className="detail-stat">
              <div className="tech-label">Your entry</div>
              <div className="detail-stat-value">{formatCurrency(detail.entryPrice)}</div>
            </div>
          )}
          {detail.confidence != null && (
            <div className="detail-stat">
              <div className="tech-label">Confidence</div>
              <div className="detail-stat-value">{formatPercent(detail.confidence, 0)}</div>
            </div>
          )}
        </div>

        {(detail.stopLoss != null || detail.takeProfit != null) && (
          <div className="detail-stat-row">
            <div className="detail-stat">
              <div className="tech-label">Stop-loss</div>
              <div className="detail-stat-value neg">
                {detail.stopLoss != null ? formatCurrency(detail.stopLoss) : '—'}
              </div>
            </div>
            <div className="detail-stat">
              <div className="tech-label">Target</div>
              <div className="detail-stat-value pos">
                {detail.takeProfit != null ? formatCurrency(detail.takeProfit) : '—'}
              </div>
            </div>
          </div>
        )}

        <div className="section-label" style={{ marginTop: '1.1rem' }}>Price chart</div>
        {candles.isLoading ? (
          <Loading />
        ) : candles.error ? (
          <ErrorBox error={candles.error} />
        ) : (
          <PricePerformance symbol={detail.symbol} candles={candles.data ?? []} />
        )}
      </div>
    </Modal>
  )
}
