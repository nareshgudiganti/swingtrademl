// The "Prices from ..." badge in the top bar, on every TradeMind page: tells a beginner whether the prices behind
// the page are fresh or out of date. Display only. The wording and the trading-day counting live in pricesAge.ts.
import { useMarketSession } from './live'
import { istToday, pricesAge } from './pricesAge'

export default function PricesBadge() {
  const market = useMarketSession()
  if (!market.data) return null
  const age = pricesAge({
    latestCandleDate: market.data.latest_candle_date ?? null,
    today: market.data.today ?? istToday(new Date()),
    recentClosedTradingDays: market.data.recent_closed_trading_days ?? [market.data.last_closed_trading_day],
  })
  return (
    <span
      className={`tm-asof ${age.tone === 'stale' ? 'tm-asof-stale' : ''}`}
      title={age.detail}
      aria-label={`${age.label}. ${age.detail}`}
      data-testid="prices-badge"
    >
      <span className="tm-asof-long">{age.label}</span>
      <span className="tm-asof-short" aria-hidden="true">
        {age.short}
      </span>
    </span>
  )
}
